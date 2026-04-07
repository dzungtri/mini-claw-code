from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .agent import AgentDone, AgentError, AgentEvent, AgentTextDelta, AgentToolCall, tool_summary
from .mock import MockProvider
from .types import AssistantTurn, Message, StopReason, ToolCall, ToolDefinition, ToolSet


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class ToolCallStart:
    index: int
    id: str
    name: str


@dataclass(slots=True)
class ToolCallDelta:
    index: int
    arguments: str


@dataclass(slots=True)
class StreamDone:
    pass


StreamEvent = TextDelta | ToolCallStart | ToolCallDelta | StreamDone


@dataclass(slots=True)
class PartialToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


class StreamAccumulator:
    def __init__(self) -> None:
        self.text = ""
        self.tool_calls: list[PartialToolCall] = []

    def feed(self, event: StreamEvent) -> None:
        if isinstance(event, TextDelta):
            self.text += event.text
        elif isinstance(event, ToolCallStart):
            while len(self.tool_calls) <= event.index:
                self.tool_calls.append(PartialToolCall())
            self.tool_calls[event.index].id = event.id
            self.tool_calls[event.index].name = event.name
        elif isinstance(event, ToolCallDelta):
            if event.index < len(self.tool_calls):
                self.tool_calls[event.index].arguments += event.arguments

    def finish(self) -> AssistantTurn:
        text = self.text or None
        tool_calls = [
            ToolCall(
                id=call.id,
                name=call.name,
                arguments=_decode_json(call.arguments),
            )
            for call in self.tool_calls
            if call.name
        ]
        stop_reason = StopReason.TOOL_USE if tool_calls else StopReason.STOP
        return AssistantTurn(text=text, tool_calls=tool_calls, stop_reason=stop_reason)


def parse_sse_line(line: str) -> list[StreamEvent] | None:
    if not line.startswith("data: "):
        return None

    data = line[len("data: ") :]
    if data == "[DONE]":
        return [StreamDone()]

    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None

    choices = chunk.get("choices") or []
    if not choices:
        return None

    delta = (choices[0] or {}).get("delta") or {}
    events: list[StreamEvent] = []

    content = delta.get("content")
    if isinstance(content, str) and content:
        events.append(TextDelta(content))

    for tool_call in delta.get("tool_calls") or []:
        index = tool_call.get("index")
        if not isinstance(index, int):
            continue
        call_id = tool_call.get("id")
        function = tool_call.get("function") or {}
        if isinstance(call_id, str):
            events.append(
                ToolCallStart(
                    index=index,
                    id=call_id,
                    name=function.get("name") or "",
                )
            )
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            events.append(ToolCallDelta(index=index, arguments=arguments))

    return events or None


class StreamProvider(Protocol):
    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        queue: "asyncio.Queue[StreamEvent]",
    ) -> AssistantTurn:
        ...


class MockStreamProvider(StreamProvider):
    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self.inner = MockProvider(responses)

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        queue: "asyncio.Queue[StreamEvent]",
    ) -> AssistantTurn:
        turn = await self.inner.chat(messages, tools)
        if turn.text:
            for char in turn.text:
                await queue.put(TextDelta(char))
        for index, call in enumerate(turn.tool_calls):
            await queue.put(ToolCallStart(index=index, id=call.id, name=call.name))
            await queue.put(ToolCallDelta(index=index, arguments=json.dumps(call.arguments)))
        await queue.put(StreamDone())
        return turn


class StreamingAgent:
    def __init__(self, provider: StreamProvider) -> None:
        self.provider = provider
        self.tools = ToolSet()

    def tool(self, tool: object) -> "StreamingAgent":
        self.tools.push(tool)  # type: ignore[arg-type]
        return self

    async def run(
        self,
        prompt: str,
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        return await self.chat([Message.user(prompt)], events)

    async def chat(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        defs = self.tools.definitions()

        while True:
            stream_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

            async def forward() -> None:
                while True:
                    event = await stream_queue.get()
                    if isinstance(event, TextDelta):
                        await events.put(AgentTextDelta(event.text))
                    if isinstance(event, StreamDone):
                        return

            forwarder = asyncio.create_task(forward())

            try:
                turn = await self.provider.stream_chat(messages, defs, stream_queue)
            except Exception as exc:
                await events.put(AgentError(str(exc)))
                forwarder.cancel()
                raise

            await forwarder

            if turn.stop_reason is StopReason.STOP:
                text = turn.text or ""
                await events.put(AgentDone(text))
                messages.append(Message.assistant(turn))
                return text

            results: list[tuple[str, str]] = []
            for call in turn.tool_calls:
                await events.put(AgentToolCall(call.name, tool_summary(call)))
                tool = self.tools.get(call.name)
                if tool is None:
                    content = f"error: unknown tool `{call.name}`"
                else:
                    try:
                        content = await tool.call(call.arguments)
                    except Exception as exc:
                        content = f"error: {exc}"
                results.append((call.id, content))

            messages.append(Message.assistant(turn))
            for call_id, content in results:
                messages.append(Message.tool_result(call_id, content))


def _decode_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
