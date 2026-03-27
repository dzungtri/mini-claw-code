import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    Message,
    MockInputHandler,
    MockStreamProvider,
    StopReason,
    ToolCall,
    render_control_plane_prompt_section,
)
from mini_claw_code_py.agent import AgentNotice
from mini_claw_code_py.types import AssistantTurn


def test_ch24_render_control_plane_prompt_section_mentions_clarify_and_verify() -> None:
    section = render_control_plane_prompt_section()

    assert "<control_plane>" in section
    assert "Clarify before acting" in section
    assert "Verify important file changes" in section


@pytest.mark.asyncio
async def test_ch24_control_plane_can_block_overwrite_without_approval(tmp_path: Path) -> None:
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
    messages = [Message.user("Overwrite the file")]

    result = await agent.execute(messages, queue)

    assert result == "Stopped."
    assert target.read_text(encoding="utf-8") == "original"
    assert any(
        message.kind == "tool_result" and message.content == "error: user denied approval"
        for message in messages
    )
    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Approval required:") for message in notices)
    assert any(message.startswith("Approval denied:") for message in notices)


@pytest.mark.asyncio
async def test_ch24_control_plane_allows_overwrite_after_approval(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("original", encoding="utf-8")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="write", arguments={"path": str(target), "content": "updated"})
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
        .enable_core_tools(MockInputHandler(deque(["Approve"])))
        .enable_control_plane()
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Overwrite the file")]

    result = await agent.execute(messages, queue)

    assert result == "Done."
    assert target.read_text(encoding="utf-8") == "updated"


@pytest.mark.asyncio
async def test_ch24_control_plane_blocks_repeated_tool_loop(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="read", arguments={"path": str(target)})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c2", name="read", arguments={"path": str(target)})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c3", name="read", arguments={"path": str(target)})],
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
        .enable_control_plane(warn_repeated_tool_calls=2, block_repeated_tool_calls=3)
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Read repeatedly")]

    await agent.execute(messages, queue)

    assert any(
        message.kind == "tool_result" and message.content == "error: control plane blocked a repeated tool-call loop"
        for message in messages
    )
    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Loop warning:") for message in notices)
    assert any(message.startswith("Loop blocked:") for message in notices)


@pytest.mark.asyncio
async def test_ch24_control_plane_warns_when_finalizing_without_verification(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="write", arguments={"path": str(target), "content": "hello"})
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
    messages = [Message.user("Write without verifying")]

    await agent.execute(messages, queue)

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any("without a clear verification step" in message for message in notices)
