import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    HARNESS_CORE_PROMPT_SECTION,
    HarnessAgent,
    Message,
    MockInputHandler,
    MockStreamProvider,
    StopReason,
    ToolCall,
)
from mini_claw_code_py.types import AssistantTurn


def test_ch18_enable_core_tools_with_handler_registers_default_profile() -> None:
    agent = HarnessAgent(MockStreamProvider(deque())).enable_core_tools(
        MockInputHandler(deque(["yes"]))
    )

    names = [definition.name for definition in agent.tools.definitions()]

    assert names == ["read", "write", "edit", "bash", "ask_user"]
    assert HARNESS_CORE_PROMPT_SECTION in agent.execution_system_prompt
    assert HARNESS_CORE_PROMPT_SECTION in agent.plan_system_prompt


def test_ch18_enable_core_tools_without_handler_skips_ask_user() -> None:
    agent = HarnessAgent(MockStreamProvider(deque())).enable_core_tools()

    names = [definition.name for definition in agent.tools.definitions()]

    assert names == ["read", "write", "edit", "bash"]


def test_ch18_enable_core_tools_is_idempotent_and_can_add_ask_user_later() -> None:
    agent = HarnessAgent(MockStreamProvider(deque())).enable_core_tools()
    agent.enable_core_tools()
    agent.enable_core_tools(MockInputHandler(deque(["choice"])))

    names = [definition.name for definition in agent.tools.definitions()]

    assert names == ["read", "write", "edit", "bash", "ask_user"]
    assert agent.execution_system_prompt.count("<harness_core_tools>") == 1


@pytest.mark.asyncio
async def test_ch18_harness_execute_uses_bundled_read_tool(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello harness", encoding="utf-8")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="read", arguments={"path": str(target)})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Read complete.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Read the file")]

    result = await agent.execute(messages, queue)

    assert result == "Read complete."
    assert any(message.kind == "tool_result" and message.content == "hello harness" for message in messages)


@pytest.mark.asyncio
async def test_ch18_harness_plan_blocks_write_tool(tmp_path: Path) -> None:
    target = tmp_path / "blocked.txt"
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Plan first",
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
                    text="Planning complete.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Plan the change")]

    result = await agent.plan(messages, queue)

    assert result == "Planning complete."
    assert not target.exists()
