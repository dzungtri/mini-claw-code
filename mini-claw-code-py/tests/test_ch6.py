import json

import httpx
import pytest

from mini_claw_code_py import AssistantTurn, Message, OpenRouterProvider, StopReason, ToolCall, ToolDefinition


def test_ch6_convert_messages() -> None:
    turn = AssistantTurn(
        text=None,
        tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "x.txt"})],
        stop_reason=StopReason.TOOL_USE,
    )
    converted = OpenRouterProvider.convert_messages(
        [Message.user("hello"), Message.assistant(turn), Message.tool_result("c1", "result")]
    )
    assert converted[0]["role"] == "user"
    assert converted[1]["role"] == "assistant"
    assert converted[1]["tool_calls"][0]["function"]["name"] == "read"
    assert converted[2]["role"] == "tool"


def test_ch6_convert_tools() -> None:
    tool = ToolDefinition.new("test_tool", "A test tool")
    converted = OpenRouterProvider.convert_tools([tool])
    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_ch6_chat_mock_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "test-model"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "Hello from mock!", "tool_calls": None},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OpenRouterProvider("key", "test-model", client=client).with_base_url(
        "https://example.test"
    )
    turn = await provider.chat([Message.user("hello")], [])
    assert turn.text == "Hello from mock!"
    assert turn.stop_reason is StopReason.STOP
    await provider.aclose()


@pytest.mark.asyncio
async def test_ch6_stream_chat_mock_transport() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        body = "\n\n".join(
            [
                'data: {"choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}',
                'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":null}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OpenRouterProvider("key", "test-model", client=client).with_base_url(
        "https://example.test"
    )

    import asyncio

    queue: asyncio.Queue[object] = asyncio.Queue()
    turn = await provider.stream_chat([Message.user("hello")], [], queue)
    assert turn.text == "Hello"
    assert turn.stop_reason is StopReason.STOP
    await provider.aclose()
