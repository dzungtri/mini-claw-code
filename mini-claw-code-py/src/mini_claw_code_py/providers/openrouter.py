from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Sequence

import httpx

from ..types import AssistantTurn, Message, Provider, StopReason, ToolCall, ToolDefinition


class OpenRouterProvider(Provider):
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    OPENAI_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_OPENROUTER_MODEL = "openrouter/free"
    DEFAULT_OPENAI_MODEL = "gpt-5-mini-2025-08-07"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = self.OPENROUTER_BASE_URL
        self.client = client or httpx.AsyncClient(timeout=60.0)

    def with_base_url(self, url: str) -> "OpenRouterProvider":
        self.base_url = url
        return self

    @staticmethod
    def _read_non_empty_env(name: str) -> str | None:
        value = os.getenv(name)
        if value is None:
            return None
        value = value.strip()
        return value or None

    @classmethod
    def _load_dotenv(cls) -> None:
        for directory in [Path.cwd(), *Path.cwd().parents]:
            dotenv_path = directory / ".env"
            if dotenv_path.is_file():
                for line in dotenv_path.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[len("export ") :].strip()
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if not key or key in os.environ:
                        continue
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                        value = value[1:-1]
                    os.environ[key] = value
                return

    @classmethod
    def from_env_with_model(cls, model: str) -> "OpenRouterProvider":
        cls._load_dotenv()
        openrouter_key = cls._read_non_empty_env("OPENROUTER_API_KEY")
        if openrouter_key is not None:
            return cls(openrouter_key, model)

        openai_key = cls._read_non_empty_env("OPENAI_API_KEY")
        if openai_key is not None:
            return cls(openai_key, model).with_base_url(cls.OPENAI_BASE_URL)

        raise RuntimeError(
            "No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY in the environment."
        )

    @classmethod
    def from_env(cls) -> "OpenRouterProvider":
        cls._load_dotenv()
        openrouter_key = cls._read_non_empty_env("OPENROUTER_API_KEY")
        if openrouter_key is not None:
            model = cls._read_non_empty_env("OPENROUTER_MODEL") or cls.DEFAULT_OPENROUTER_MODEL
            return cls(openrouter_key, model)

        openai_key = cls._read_non_empty_env("OPENAI_API_KEY")
        if openai_key is not None:
            model = cls._read_non_empty_env("OPENAI_MODEL") or cls.DEFAULT_OPENAI_MODEL
            return cls(openai_key, model).with_base_url(cls.OPENAI_BASE_URL)

        raise RuntimeError(
            "No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY in the environment."
        )

    @staticmethod
    def convert_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.kind == "system":
                converted.append(
                    {
                        "role": "system",
                        "content": message.content,
                    }
                )
            elif message.kind == "user":
                converted.append(
                    {
                        "role": "user",
                        "content": message.content,
                    }
                )
            elif message.kind == "assistant":
                turn = message.turn
                assert turn is not None
                tool_calls = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in turn.tool_calls
                ]
                converted.append(
                    {
                        "role": "assistant",
                        "content": turn.text,
                        "tool_calls": tool_calls or None,
                    }
                )
            elif message.kind == "tool_result":
                converted.append(
                    {
                        "role": "tool",
                        "content": message.content,
                        "tool_call_id": message.tool_call_id,
                    }
                )
            else:
                raise ValueError(f"unknown message kind: {message.kind}")
        return converted

    @staticmethod
    def convert_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        body = {
            "model": self.model,
            "messages": self.convert_messages(messages),
            "tools": self.convert_tools(tools),
            "stream": False,
        }

        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("no choices in response")

        choice = choices[0]
        message = choice.get("message") or {}
        api_tool_calls = message.get("tool_calls") or []

        tool_calls = [
            ToolCall(
                id=tool_call["id"],
                name=tool_call["function"]["name"],
                arguments=_decode_tool_arguments(tool_call["function"]["arguments"]),
            )
            for tool_call in api_tool_calls
        ]

        finish_reason = choice.get("finish_reason")
        stop_reason = (
            StopReason.TOOL_USE if finish_reason == "tool_calls" else StopReason.STOP
        )
        return AssistantTurn(
            text=message.get("content"),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        queue: "asyncio.Queue[object]",
    ) -> AssistantTurn:
        from ..streaming import StreamAccumulator, parse_sse_line

        body = {
            "model": self.model,
            "messages": self.convert_messages(messages),
            "tools": self.convert_tools(tools),
            "stream": True,
        }

        accumulator = StreamAccumulator()

        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line:
                    continue
                events = parse_sse_line(line)
                if events is None:
                    continue
                for event in events:
                    accumulator.feed(event)
                    await queue.put(event)

        return accumulator.finish()

    async def aclose(self) -> None:
        await self.client.aclose()


def _decode_tool_arguments(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
