import asyncio
import json
from collections import deque
from pathlib import Path
from typing import Sequence

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    Message,
    StopReason,
    render_harness_subagent_prompt_section,
)
from mini_claw_code_py.agent import AgentNotice
from mini_claw_code_py.streaming import StreamDone, TextDelta, ToolCallDelta, ToolCallStart
from mini_claw_code_py.types import AssistantTurn, ToolCall, ToolDefinition


class HybridProvider:
    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self._responses = responses
        self.chat_calls: list[list[Message]] = []

    async def chat(
        self,
        messages: Sequence[Message],
        _tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        self.chat_calls.append(list(messages))
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


def test_ch22_render_harness_subagent_prompt_section_mentions_limit() -> None:
    section = render_harness_subagent_prompt_section(3)

    assert "<subagent_orchestration>" in section
    assert "Launch at most 3 subagent call(s)" in section
    assert "The user does not need to mention `subagent`." in section
    assert "DECOMPOSE" in section


def test_ch22_enable_subagents_adds_prompt_and_tool() -> None:
    provider = HybridProvider(deque())
    agent = HarnessAgent(provider).enable_core_tools().enable_subagents()

    names = [definition.name for definition in agent.tools.definitions()]

    assert "subagent" in names
    assert "<subagent_orchestration>" in agent.execution_system_prompt


@pytest.mark.asyncio
async def test_ch22_planning_mode_can_update_todo_list() -> None:
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text="Drafting plan",
                    tool_calls=[
                        ToolCall(
                            id="t1",
                            name="write_todos",
                            arguments={
                                "items": [
                                    {"content": "Inspect the repo", "status": "completed"},
                                    {"content": "Draft the plan", "status": "in_progress"},
                                ]
                            },
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Planning complete.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_subagents()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Plan the work")]

    result = await agent.plan(messages, queue)

    assert result == "Planning complete."
    assert [item.content for item in agent.todo_board().items()] == [
        "Inspect the repo",
        "Draft the plan",
    ]
    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Planning mode active:") for message in notices)
    assert any(message.startswith("Todo list updated:") for message in notices)


@pytest.mark.asyncio
async def test_ch22_harness_subagent_executes_child_and_parent_continues(tmp_path: Path) -> None:
    target = tmp_path / "child.txt"
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="p1", name="subagent", arguments={"task": f"Write {target} with child content"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write",
                            arguments={"path": str(target), "content": "from child"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Child completed the delegated write.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text="Parent final answer.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_subagents()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Delegate the write")]

    result = await agent.execute(messages, queue)

    assert result == "Parent final answer."
    assert target.read_text(encoding="utf-8") == "from child"
    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Subagent started") for message in notices)
    assert any(message.startswith("Subagent finished") for message in notices)


@pytest.mark.asyncio
async def test_ch22_execute_marks_todos_completed_before_final_answer() -> None:
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text="I will track progress first.",
                    tool_calls=[
                        ToolCall(
                            id="t1",
                            name="write_todos",
                            arguments={
                                "items": [
                                    "Create four poem files (in_progress)",
                                    "Verify the outputs exist",
                                ]
                            },
                        )
                    ],
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
    agent = HarnessAgent(provider).enable_core_tools()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Write four poems")]

    result = await agent.execute(messages, queue)

    assert result == "Done."
    assert [item.status for item in agent.todo_board().items()] == ["completed", "completed"]
    assert [item.content for item in agent.todo_board().items()] == [
        "Create four poem files",
        "Verify the outputs exist",
    ]
    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any("Todo list updated:" in message for message in notices)
    assert any("- [x] Create four poem files" in message for message in notices)


@pytest.mark.asyncio
async def test_ch22_harness_subagent_limit_applies_per_turn() -> None:
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="p1", name="subagent", arguments={"task": "Task 1"}),
                        ToolCall(id="p2", name="subagent", arguments={"task": "Task 2"}),
                        ToolCall(id="p3", name="subagent", arguments={"task": "Task 3"}),
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(text="Child 1 done", tool_calls=[], stop_reason=StopReason.STOP),
                AssistantTurn(text="Child 2 done", tool_calls=[], stop_reason=StopReason.STOP),
                AssistantTurn(text="Parent final", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_subagents(max_parallel_subagents=2)
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Delegate multiple tasks")]

    result = await agent.execute(messages, queue)

    assert result == "Parent final"
    tool_results = [message.content for message in messages if message.kind == "tool_result"]
    assert "Child 1 done" in tool_results
    assert "Child 2 done" in tool_results
    assert any("too many subagent calls" in (content or "") for content in tool_results)

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Subagent limit applied:") for message in notices)


@pytest.mark.asyncio
async def test_ch22_subagent_child_scope_can_be_narrowed_to_read_only(tmp_path: Path) -> None:
    target = tmp_path / "blocked.txt"
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="p1", name="subagent", arguments={"task": "Try to write a file"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write",
                            arguments={"path": str(target), "content": "blocked"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Child finished.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text="Parent final.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_subagents(tool_names=["read", "bash"])
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Delegate carefully")]

    await agent.execute(messages, queue)

    assert not target.exists()
    child_histories = [call for call in provider.chat_calls if call and call[0].kind == "system"]
    assert any(
        any(
            message.kind == "tool_result" and "unknown tool `write`" in (message.content or "")
            for message in history
        )
        for history in child_histories
    )


@pytest.mark.asyncio
async def test_ch22_planning_mode_keeps_subagent_unavailable() -> None:
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text="Plan draft",
                    tool_calls=[
                        ToolCall(id="p1", name="subagent", arguments={"task": "Investigate"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Planning complete.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_subagents()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Plan the work")]

    result = await agent.plan(messages, queue)

    assert result == "Planning complete."
    tool_results = [message.content for message in messages if message.kind == "tool_result"]
    assert any("tool 'subagent' is not available in planning mode" in (content or "") for content in tool_results)
