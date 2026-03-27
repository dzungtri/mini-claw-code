import asyncio
from collections import deque
from pathlib import Path
from typing import Sequence

import pytest

from mini_claw_code_py import (
    AgentApprovalUpdate,
    AgentContextCompaction,
    AgentMemoryUpdate,
    AgentTodoUpdate,
    HarnessAgent,
    Message,
    MockInputHandler,
    MockStreamProvider,
    StopReason,
    ToolCall,
    ToolDefinition,
)
from mini_claw_code_py.types import AssistantTurn


class MockChatStreamProvider(MockStreamProvider):
    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        return await self.inner.chat(messages, tools)


@pytest.mark.asyncio
async def test_ch27_emits_structured_approval_events(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("original", encoding="utf-8")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="write", arguments={"path": str(target), "content": "blocked"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Stopped.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools(MockInputHandler(deque(["Cancel"])))
        .enable_control_plane()
    )
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("Overwrite the file")], queue)

    statuses: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentApprovalUpdate):
            statuses.append(event.status)
    assert statuses == ["required", "denied"]


@pytest.mark.asyncio
async def test_ch27_emits_structured_todo_events() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_todos",
                            arguments={
                                "items": [
                                    {"content": "Inspect files", "status": "completed"},
                                    {"content": "Edit implementation", "status": "in_progress"},
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

    await agent.execute([Message.user("Track work")], queue)

    todo_events: list[AgentTodoUpdate] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentTodoUpdate):
            todo_events.append(event)
    assert len(todo_events) >= 1
    assert todo_events[0].total == 2


@pytest.mark.asyncio
async def test_ch27_emits_structured_memory_events(tmp_path: Path) -> None:
    project_memory = tmp_path / ".agents" / "AGENTS.md"
    project_memory.parent.mkdir(parents=True)
    project_memory.write_text("# Project Memory\n", encoding="utf-8")

    provider = MockChatStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="I will remember that.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text='{"should_write": true, "lines": ["Prefer concise answers."]}',
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_project_memory_file(project_memory)
        .enable_memory_updates(debounce_seconds=0.0, target_scope="project")
    )
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("Remember that I prefer concise answers.")], queue)
    await agent.flush_memory_updates()

    foreground_statuses: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentMemoryUpdate):
            foreground_statuses.append(event.status)

    background_statuses: list[str] = []
    notice_queue = agent.notice_queue()
    while not notice_queue.empty():
        event = notice_queue.get_nowait()
        if isinstance(event, AgentMemoryUpdate):
            background_statuses.append(event.status)

    assert foreground_statuses == ["queued"]
    assert background_statuses == ["updated"]


@pytest.mark.asyncio
async def test_ch27_emits_structured_context_compaction_events() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = HarnessAgent(provider).enable_context_durability(max_messages=4, keep_recent=2)
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [
        Message.user("one"),
        Message.assistant(AssistantTurn(text="a", tool_calls=[], stop_reason=StopReason.STOP)),
        Message.user("two"),
        Message.assistant(AssistantTurn(text="b", tool_calls=[], stop_reason=StopReason.STOP)),
        Message.user("three"),
    ]

    await agent.execute(messages, queue)

    compactions: list[AgentContextCompaction] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentContextCompaction):
            compactions.append(event)
    assert len(compactions) == 1
    assert compactions[0].archived_messages > 0
