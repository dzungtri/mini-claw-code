from collections import deque

import pytest

from mini_claw_code_py import (
    AgentDone,
    AgentTextDelta,
    MockStreamProvider,
    StopReason,
    StreamAccumulator,
    StreamDone,
    StreamingAgent,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    WriteTool,
    parse_sse_line,
)
from mini_claw_code_py.types import AssistantTurn, ToolCall


def test_ch10_accumulator_text() -> None:
    acc = StreamAccumulator()
    acc.feed(TextDelta("Hello"))
    acc.feed(TextDelta(" world"))
    acc.feed(StreamDone())
    turn = acc.finish()
    assert turn.text == "Hello world"
    assert turn.stop_reason is StopReason.STOP


def test_ch10_accumulator_tool_call() -> None:
    acc = StreamAccumulator()
    acc.feed(ToolCallStart(index=0, id="call_1", name="read"))
    acc.feed(ToolCallDelta(index=0, arguments='{"pa'))
    acc.feed(ToolCallDelta(index=0, arguments='th": "f.txt"}'))
    acc.feed(StreamDone())
    turn = acc.finish()
    assert turn.tool_calls[0].name == "read"
    assert turn.tool_calls[0].arguments["path"] == "f.txt"
    assert turn.stop_reason is StopReason.TOOL_USE


def test_ch10_parse_sse_line() -> None:
    events = parse_sse_line(
        'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}'
    )
    assert events == [TextDelta("Hello")]


@pytest.mark.asyncio
async def test_ch10_streaming_agent() -> None:
    provider = MockStreamProvider(
        deque([AssistantTurn(text="Hello!", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    agent = StreamingAgent(provider).tool(WriteTool())
    queue: asyncio.Queue[object]
    import asyncio

    queue = asyncio.Queue()
    result = await agent.run("Hi", queue)
    first = await queue.get()
    assert isinstance(first, AgentTextDelta)
    while not isinstance((event := await queue.get()), AgentDone):
        pass
    assert result == "Hello!"
