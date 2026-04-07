from collections import deque

import pytest

from mini_claw_code_starter_py import AssistantTurn, Message, MockProvider, StopReason, ToolCall


@pytest.mark.asyncio
async def test_ch1_returns_text() -> None:
    provider = MockProvider.new(
        deque([AssistantTurn(text="Hello, world!", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    turn = await provider.chat([Message.user("Hi")], [])
    assert turn.text == "Hello, world!"
    assert turn.tool_calls == []


@pytest.mark.asyncio
async def test_ch1_returns_tool_calls() -> None:
    provider = MockProvider.new(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="call_1", name="read", arguments={"path": "test.txt"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                )
            ]
        )
    )
    turn = await provider.chat([Message.user("read test.txt")], [])
    assert turn.text is None
    assert turn.tool_calls[0].name == "read"

