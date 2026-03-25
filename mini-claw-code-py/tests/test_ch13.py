from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import MockProvider, ReadTool, StopReason, SubagentTool, ToolSet
from mini_claw_code_py.types import AssistantTurn, ToolCall


@pytest.mark.asyncio
async def test_ch13_subagent_text_response() -> None:
    provider = MockProvider(
        deque([AssistantTurn(text="Child result", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    tool = SubagentTool(provider, lambda: ToolSet())
    assert await tool.call({"task": "Do something"}) == "Child result"


@pytest.mark.asyncio
async def test_ch13_subagent_with_tool(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("secret data")
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="read", arguments={"path": str(path)})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="The file says: secret data",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    tool = SubagentTool(provider, lambda: ToolSet().with_tool(ReadTool()))
    assert await tool.call({"task": "Read the file"}) == "The file says: secret data"
