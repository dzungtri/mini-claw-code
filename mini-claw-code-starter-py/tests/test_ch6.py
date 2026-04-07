from mini_claw_code_starter_py import Message, OpenRouterProvider, ToolDefinition


def test_ch6_new() -> None:
    provider = OpenRouterProvider.new("test-key", "test-model")
    assert provider.model == "test-model"


def test_ch6_convert_messages() -> None:
    converted = OpenRouterProvider.convert_messages(
        [
            Message.user("hello"),
            Message.tool_result("call_1", "result"),
        ]
    )
    assert converted[0]["role"] == "user"
    assert converted[1]["role"] == "tool"


def test_ch6_convert_tools() -> None:
    tool = ToolDefinition.new("test_tool", "A test tool")
    converted = OpenRouterProvider.convert_tools([tool])
    assert converted[0]["type"] == "function"
