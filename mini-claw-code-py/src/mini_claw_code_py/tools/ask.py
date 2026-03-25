from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..types import ToolDefinition


class InputHandler(Protocol):
    async def ask(self, question: str, options: Sequence[str]) -> str:
        ...


class AskTool:
    def __init__(self, handler: InputHandler) -> None:
        self.handler = handler
        self._definition = (
            ToolDefinition.new(
                "ask_user",
                "Ask the user a clarifying question. Use this when you need more "
                "information before proceeding.",
            )
            .param("question", "string", "The question to ask the user", True)
            .param_raw(
                "options",
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of choices to present to the user",
                },
                False,
            )
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        question = args.get("question") if isinstance(args, dict) else None
        if not isinstance(question, str):
            raise ValueError("missing required parameter: question")
        options = parse_options(args)
        return await self.handler.ask(question, options)


def parse_options(args: Any) -> list[str]:
    if not isinstance(args, dict):
        return []
    raw = args.get("options")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


class CliInputHandler:
    async def ask(self, question: str, options: Sequence[str]) -> str:
        def _read() -> str:
            print(f"\n  {question}")
            for index, option in enumerate(options, start=1):
                print(f"    {index}) {option}")
            answer = input("  > ").strip()
            return resolve_option(answer, options)

        return await asyncio.to_thread(_read)


def resolve_option(answer: str, options: Sequence[str]) -> str:
    try:
        index = int(answer)
    except ValueError:
        return answer
    if 1 <= index <= len(options):
        return options[index - 1]
    return answer


@dataclass(slots=True)
class UserInputRequest:
    question: str
    options: list[str]
    response_future: asyncio.Future[str]


class ChannelInputHandler:
    def __init__(self, queue: "asyncio.Queue[UserInputRequest]") -> None:
        self.queue = queue

    async def ask(self, question: str, options: Sequence[str]) -> str:
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[str] = loop.create_future()
        await self.queue.put(
            UserInputRequest(
                question=question,
                options=list(options),
                response_future=response_future,
            )
        )
        return await response_future


class MockInputHandler:
    def __init__(self, answers: deque[str]) -> None:
        self.answers = answers
        self.lock = asyncio.Lock()

    async def ask(self, _question: str, _options: Sequence[str]) -> str:
        async with self.lock:
            if not self.answers:
                raise RuntimeError("MockInputHandler: no more answers")
            return self.answers.popleft()
