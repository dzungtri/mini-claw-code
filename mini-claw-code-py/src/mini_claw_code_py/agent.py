from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Sequence

from .types import AssistantTurn, Message, Provider, StopReason, ToolCall, ToolSet


@dataclass(slots=True)
class AgentTextDelta:
    text: str


@dataclass(slots=True)
class AgentToolCall:
    name: str
    summary: str


@dataclass(slots=True)
class AgentDone:
    text: str


@dataclass(slots=True)
class AgentError:
    error: str


AgentEvent = AgentTextDelta | AgentToolCall | AgentDone | AgentError


def tool_summary(call: ToolCall) -> str:
    detail = None
    if isinstance(call.arguments, dict):
        detail = (
            call.arguments.get("command")
            or call.arguments.get("path")
            or call.arguments.get("question")
        )
    if isinstance(detail, str):
        return f"    [{call.name}: {detail}]"
    return f"    [{call.name}]"


async def single_turn(provider: Provider, tools: ToolSet, prompt: str) -> str:
    defs = tools.definitions()
    messages = [Message.user(prompt)]
    turn = await provider.chat(messages, defs)

    if turn.stop_reason is StopReason.STOP:
        return turn.text or ""

    results: list[tuple[str, str]] = []
    for call in turn.tool_calls:
        print(f"\x1b[2K\r{tool_summary(call)}")
        tool = tools.get(call.name)
        if tool is None:
            content = f"error: unknown tool `{call.name}`"
        else:
            try:
                content = await tool.call(call.arguments)
            except Exception as exc:  # pragma: no cover - exercised by tests
                content = f"error: {exc}"
        results.append((call.id, content))

    messages.append(Message.assistant(turn))
    for call_id, content in results:
        messages.append(Message.tool_result(call_id, content))

    final_turn = await provider.chat(messages, defs)
    return final_turn.text or ""


class SimpleAgent:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.tools = ToolSet()

    def tool(self, tool: object) -> "SimpleAgent":
        self.tools.push(tool)  # type: ignore[arg-type]
        return self

    async def execute_tools(self, calls: Sequence[ToolCall]) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for call in calls:
            tool = self.tools.get(call.name)
            if tool is None:
                content = f"error: unknown tool `{call.name}`"
            else:
                try:
                    content = await tool.call(call.arguments)
                except Exception as exc:
                    content = f"error: {exc}"
            results.append((call.id, content))
        return results

    @staticmethod
    def push_results(
        messages: list[Message],
        turn: AssistantTurn,
        results: list[tuple[str, str]],
    ) -> None:
        messages.append(Message.assistant(turn))
        for call_id, content in results:
            messages.append(Message.tool_result(call_id, content))

    async def run_with_history(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> list[Message]:
        defs = self.tools.definitions()

        while True:
            try:
                turn = await self.provider.chat(messages, defs)
            except Exception as exc:
                await events.put(AgentError(str(exc)))
                return messages

            if turn.stop_reason is StopReason.STOP:
                text = turn.text or ""
                await events.put(AgentDone(text))
                messages.append(Message.assistant(turn))
                return messages

            for call in turn.tool_calls:
                await events.put(AgentToolCall(call.name, tool_summary(call)))

            results = await self.execute_tools(turn.tool_calls)
            self.push_results(messages, turn, results)

    async def run_with_events(
        self,
        prompt: str,
        events: "asyncio.Queue[AgentEvent]",
    ) -> None:
        await self.run_with_history([Message.user(prompt)], events)

    async def chat(self, messages: list[Message]) -> str:
        defs = self.tools.definitions()

        while True:
            turn = await self.provider.chat(messages, defs)

            if turn.stop_reason is StopReason.STOP:
                text = turn.text or ""
                messages.append(Message.assistant(turn))
                return text

            for call in turn.tool_calls:
                print(f"\x1b[2K\r{tool_summary(call)}")

            results = await self.execute_tools(turn.tool_calls)
            self.push_results(messages, turn, results)

    async def run(self, prompt: str) -> str:
        messages = [Message.user(prompt)]
        return await self.chat(messages)
