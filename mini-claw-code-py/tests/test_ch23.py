import asyncio
import json
from collections import deque
from typing import Sequence

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    Message,
    StopReason,
    ToolSearchTool,
    render_tool_universe_prompt_section,
)
from mini_claw_code_py.agent import AgentNotice
from mini_claw_code_py.streaming import StreamDone, TextDelta, ToolCallDelta, ToolCallStart
from mini_claw_code_py.tool_universe import DeferredToolRegistry
from mini_claw_code_py.types import AssistantTurn, ToolCall, ToolDefinition, ToolSet


class HybridProvider:
    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self._responses = responses

    async def chat(
        self,
        _messages: Sequence[Message],
        _tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        if not self._responses:
            raise RuntimeError("HybridProvider: no more responses")
        return self._responses.popleft()

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        queue: "asyncio.Queue[object]",
    ) -> AssistantTurn:
        turn = await self.chat(messages, tools)
        if turn.text:
            for char in turn.text:
                await queue.put(TextDelta(char))
        for index, call in enumerate(turn.tool_calls):
            await queue.put(ToolCallStart(index=index, id=call.id, name=call.name))
            await queue.put(ToolCallDelta(index=index, arguments=json.dumps(call.arguments)))
        await queue.put(StreamDone())
        return turn


class FakeExternalTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition.new("docs_lookup", "Look up documentation in a deferred external catalog.")

    async def call(self, _args: object) -> str:
        return "docs ok"


class FakeMCPRegistry:
    def all(self) -> list[str]:
        return ["fake"]


class FakeMCPToolAdapter:
    def __init__(self, _registry: object) -> None:
        self._tools = [FakeExternalTool()]

    async def __aenter__(self) -> "FakeMCPToolAdapter":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def tools(self) -> list[FakeExternalTool]:
        return list(self._tools)

    def status_summary(self) -> str:
        return "MCP connected: fake (1 tool available)"


def test_ch23_render_tool_universe_prompt_section_mentions_tool_search() -> None:
    section = render_tool_universe_prompt_section()

    assert "<tool_universe_system>" in section
    assert "tool_search" in section
    assert "select:name1,name2" in section


@pytest.mark.asyncio
async def test_ch23_tool_search_can_search_and_activate_deferred_tools() -> None:
    registry = DeferredToolRegistry()
    runtime_tools = ToolSet()
    registry.register(FakeExternalTool(), source="mcp")
    tool = ToolSearchTool(registry, runtime_tools)

    search_result = await tool.call({"query": "docs"})
    activate_result = await tool.call({"query": "select:docs_lookup"})

    assert "docs_lookup" in search_result
    assert "Activated deferred tools" in activate_result
    assert runtime_tools.get("docs_lookup") is not None


@pytest.mark.asyncio
async def test_ch23_harness_defers_external_tools_until_tool_search(monkeypatch: pytest.MonkeyPatch) -> None:
    import mini_claw_code_py.harness as harness_mod

    monkeypatch.setattr(harness_mod, "MCPToolAdapter", FakeMCPToolAdapter)

    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="tool_search", arguments={"query": "docs"})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c2", name="tool_search", arguments={"query": "select:docs_lookup"})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c3", name="docs_lookup", arguments={})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_tool_universe_management()
    agent._mcp_registry = FakeMCPRegistry()  # type: ignore[assignment]
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Use deferred docs tools if needed")]

    result = await agent.execute(messages, queue)

    assert result == "Done."
    tool_results = [message.content for message in messages if message.kind == "tool_result"]
    assert any("docs_lookup" in (content or "") for content in tool_results)
    assert any((content or "") == "docs ok" for content in tool_results)

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Tool universe ready:") for message in notices)
