from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Mapping, Sequence

from .events import AgentDone, AgentError, AgentEvent, AgentNotice, AgentTextDelta, AgentToolCall, tool_summary
from .mcp import MCPRegistry, MCPToolAdapter
from .types import AssistantTurn, Message, Provider, StopReason, ToolCall, ToolSet


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
        self._mcp_registry: MCPRegistry | None = None

    def tool(self, tool: object) -> "SimpleAgent":
        self.tools.push(tool)  # type: ignore[arg-type]
        return self

    def enable_default_mcp(
        self,
        cwd: Path | None = None,
        home: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> "SimpleAgent":
        self._mcp_registry = MCPRegistry.discover_default(cwd=cwd, home=home, env=env)
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
        async with AsyncExitStack() as stack:
            runtime_tools, mcp_summary = await self._runtime_tools(stack)
            defs = runtime_tools.definitions()

            if mcp_summary:
                await events.put(AgentNotice(mcp_summary))

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

                results = await self._execute_tools_with_set(runtime_tools, turn.tool_calls)
                self.push_results(messages, turn, results)

    async def run_with_events(
        self,
        prompt: str,
        events: "asyncio.Queue[AgentEvent]",
    ) -> None:
        await self.run_with_history([Message.user(prompt)], events)

    async def chat(self, messages: list[Message]) -> str:
        async with AsyncExitStack() as stack:
            runtime_tools, _ = await self._runtime_tools(stack)
            defs = runtime_tools.definitions()

            while True:
                turn = await self.provider.chat(messages, defs)

                if turn.stop_reason is StopReason.STOP:
                    text = turn.text or ""
                    messages.append(Message.assistant(turn))
                    return text

                for call in turn.tool_calls:
                    print(f"\x1b[2K\r{tool_summary(call)}")

                results = await self._execute_tools_with_set(runtime_tools, turn.tool_calls)
                self.push_results(messages, turn, results)

    async def run(self, prompt: str) -> str:
        messages = [Message.user(prompt)]
        return await self.chat(messages)

    async def _runtime_tools(self, stack: AsyncExitStack) -> tuple[ToolSet, str | None]:
        runtime_tools = self.tools.copy()
        mcp_summary: str | None = None
        if self._mcp_registry is not None and self._mcp_registry.all():
            adapter = await stack.enter_async_context(MCPToolAdapter(self._mcp_registry))
            mcp_summary = adapter.status_summary()
            for tool in adapter.tools():
                runtime_tools.push(tool)
        return runtime_tools, mcp_summary

    async def _execute_tools_with_set(
        self,
        tools: ToolSet,
        calls: Sequence[ToolCall],
    ) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for call in calls:
            tool = tools.get(call.name)
            if tool is None:
                content = f"error: unknown tool `{call.name}`"
            else:
                try:
                    content = await tool.call(call.arguments)
                except Exception as exc:
                    content = f"error: {exc}"
            results.append((call.id, content))
        return results
