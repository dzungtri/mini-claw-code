from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    AssistantTurn,
    MockProvider,
    ReadTool,
    StopReason,
    ToolCall,
    ToolSet,
    single_turn,
)


@pytest.mark.asyncio
async def test_ch3_direct_response() -> None:
    provider = MockProvider(
        deque([AssistantTurn(text="Hello!", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    assert await single_turn(provider, ToolSet(), "Hi") == "Hello!"


@pytest.mark.asyncio
async def test_ch3_one_tool_call(tmp_path: Path) -> None:
    path = tmp_path / "test.txt"
    path.write_text("file content")
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="call_1", name="read", arguments={"path": str(path)})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="The file contains: file content",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    tools = ToolSet().with_tool(ReadTool())
    assert await single_turn(provider, tools, "Read test.txt") == "The file contains: file content"


@pytest.mark.asyncio
async def test_ch3_unknown_tool() -> None:
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="call_1", name="missing", arguments={})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Sorry, that tool doesn't exist.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    assert await single_turn(provider, ToolSet(), "Use missing tool") == "Sorry, that tool doesn't exist."
