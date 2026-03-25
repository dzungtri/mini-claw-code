from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_starter_py import (
    AssistantTurn,
    Message,
    MockProvider,
    ReadTool,
    SimpleAgent,
    StopReason,
    ToolCall,
    WriteTool,
)


@pytest.mark.asyncio
async def test_ch7_write_and_read_flow(tmp_path: Path) -> None:
    path = tmp_path / "test.txt"
    provider = MockProvider.new(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="write",
                            arguments={"path": str(path), "content": "Hello from agent!"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="call_2", name="read", arguments={"path": str(path)})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="I wrote and read the file. It contains: Hello from agent!",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = SimpleAgent.new(provider).tool(WriteTool.new()).tool(ReadTool.new())
    result = await agent.run("Write and read a file")
    assert "Hello from agent!" in result


@pytest.mark.asyncio
async def test_ch7_chat_keeps_history() -> None:
    provider = MockProvider.new(
        deque(
            [
                AssistantTurn(text="first", tool_calls=[], stop_reason=StopReason.STOP),
                AssistantTurn(text="second", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    agent = SimpleAgent.new(provider)
    history = [Message.system("You are helpful.")]
    history.append(Message.user("one"))
    assert await agent.chat(history) == "first"
    history.append(Message.user("two"))
    assert await agent.chat(history) == "second"
