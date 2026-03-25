from collections import deque

import asyncio
import pytest

from mini_claw_code_py import AskTool, ChannelInputHandler, MockInputHandler, UserInputRequest


def test_ch11_ask_tool_definition() -> None:
    tool = AskTool(MockInputHandler(deque()))
    assert tool.definition.name == "ask_user"
    assert "question" in tool.definition.parameters["required"]
    assert tool.definition.parameters["properties"]["options"]["type"] == "array"


@pytest.mark.asyncio
async def test_ch11_question_only() -> None:
    tool = AskTool(MockInputHandler(deque(["Yes"])))
    assert await tool.call({"question": "Should I proceed?"}) == "Yes"


@pytest.mark.asyncio
async def test_ch11_channel_handler() -> None:
    queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    handler = ChannelInputHandler(queue)

    async def responder() -> None:
        request = await queue.get()
        request.response_future.set_result("Option B")

    task = asyncio.create_task(responder())
    answer = await handler.ask("Which approach?", ["Option A", "Option B"])
    await task
    assert answer == "Option B"
