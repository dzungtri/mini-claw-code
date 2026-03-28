import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    Message,
    MockInputHandler,
    MockProvider,
    MockStreamProvider,
    StopReason,
    ToolCall,
)
from mini_claw_code_py.agent import AgentNotice
from mini_claw_code_py.control_plane import (
    approval_message_for_tool,
    classify_loop,
    control_plane_profile,
    mutation_targets_for_tool,
    verification_clears_mutations,
    verification_targets_for_tool,
)
from mini_claw_code_py.types import AssistantTurn


def test_ch33_edit_approval_message_matches_existing_files(tmp_path: Path) -> None:
    target = tmp_path / "draft.txt"
    target.write_text("v1", encoding="utf-8")

    message = approval_message_for_tool(
        "edit",
        {"path": str(target), "find": "v1", "replace": "v2"},
        control_plane_profile("balanced"),
    )

    assert message == f"Edit existing file `{target}`?"


def test_ch33_loop_detection_counts_consecutive_repetition_only() -> None:
    settings = control_plane_profile("balanced")
    history = ["read:a", "read:a", "bash:b", "read:a"]

    assert classify_loop(history, "read:a", settings) is None
    assert classify_loop(["read:a", "read:a", "read:a"], "read:a", settings) == "warn"


def test_ch33_target_matching_is_precise_for_mutation_and_verification() -> None:
    pending = mutation_targets_for_tool("write", {"path": "src/app.py", "content": "x"})
    verify_same = verification_targets_for_tool("read", {"path": "src/app.py"})
    verify_other = verification_targets_for_tool("read", {"path": "README.md"})

    assert pending == {"src/app.py"}
    assert verification_clears_mutations(
        pending_mutations=pending,
        verification_targets=verify_same,
    )
    assert not verification_clears_mutations(
        pending_mutations=pending,
        verification_targets=verify_other,
    )


@pytest.mark.asyncio
async def test_ch33_unrelated_read_does_not_clear_missing_verification_warning(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    other = tmp_path / "README.md"
    other.write_text("hello", encoding="utf-8")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="write", arguments={"path": str(target), "content": "changed"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c2", name="read", arguments={"path": str(other)})
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
    agent = HarnessAgent(provider).enable_core_tools().enable_control_plane()
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("Write the file, then read something unrelated.")], queue)

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any("without a clear verification step" in message for message in notices)


@pytest.mark.asyncio
async def test_ch33_related_read_clears_missing_verification_warning(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="write", arguments={"path": str(target), "content": "changed"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c2", name="read", arguments={"path": str(target)})
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
    agent = HarnessAgent(provider).enable_core_tools().enable_control_plane()
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("Write the file and verify it.")], queue)

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert not any("without a clear verification step" in message for message in notices)


@pytest.mark.asyncio
async def test_ch33_read_only_subagent_does_not_trigger_verification_warning() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="subagent", arguments={"task": "Review the codebase for risks."})
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
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_subagents(
            provider=MockProvider(
                deque(
                    [
                        AssistantTurn(
                            text="Review completed.",
                            tool_calls=[],
                            stop_reason=StopReason.STOP,
                        )
                    ]
                )
            )
        )
        .enable_control_plane()
    )
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("Use a subagent to review only.")], queue)

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert not any("without a clear verification step" in message for message in notices)


@pytest.mark.asyncio
async def test_ch33_edit_requires_approval_under_balanced_profile(tmp_path: Path) -> None:
    target = tmp_path / "draft.txt"
    target.write_text("hello world", encoding="utf-8")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="edit",
                            arguments={"path": str(target), "find": "world", "replace": "team"},
                        )
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

    await agent.execute([Message.user("Edit the file.")], queue)

    assert target.read_text(encoding="utf-8") == "hello world"
