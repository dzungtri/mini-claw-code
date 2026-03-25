from collections import deque
from pathlib import Path

import asyncio
import pytest

from mini_claw_code_py import (
    AgentDone,
    Message,
    MockStreamProvider,
    PlanAgent,
    ReadTool,
    StopReason,
    ToolCall,
    WriteTool,
)
from mini_claw_code_py.types import AssistantTurn


@pytest.mark.asyncio
async def test_ch12_plan_text_response() -> None:
    provider = MockStreamProvider(
        deque([AssistantTurn(text="Here is my plan.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    agent = PlanAgent(provider).tool(ReadTool()).tool(WriteTool())
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Plan something")]
    result = await agent.plan(messages, queue)
    assert result == "Here is my plan."
    assert messages[0].kind == "system"


@pytest.mark.asyncio
async def test_ch12_plan_blocks_write_tool(tmp_path: Path) -> None:
    path = tmp_path / "blocked.txt"
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Plan first",
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write",
                            arguments={"path": str(path), "content": "data"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(text="Done planning", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    agent = PlanAgent(provider).tool(ReadTool()).tool(WriteTool())
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Plan the change")]
    result = await agent.plan(messages, queue)
    assert result == "Done planning"
    assert not path.exists()
