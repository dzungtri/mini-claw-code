from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_starter_py import (
    AssistantTurn,
    MockProvider,
    ReadTool,
    SimpleAgent,
    StopReason,
    ToolCall,
)


@pytest.mark.asyncio
async def test_ch5_text_response() -> None:
    provider = MockProvider.new(
        deque([AssistantTurn(text="Hello!", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    agent = SimpleAgent.new(provider)
    assert await agent.run("Hi") == "Hello!"


@pytest.mark.asyncio
async def test_ch5_single_tool_call(tmp_path: Path) -> None:
    path = tmp_path / "test.txt"
    path.write_text("file content")
    provider = MockProvider.new(
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
    agent = SimpleAgent.new(provider).tool(ReadTool.new())
    assert await agent.run("Read test.txt") == "The file contains: file content"
