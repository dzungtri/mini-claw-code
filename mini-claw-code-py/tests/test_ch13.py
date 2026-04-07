from collections import deque
from pathlib import Path
from typing import Sequence

import pytest

from mini_claw_code_py import (
    DEFAULT_SUBAGENT_SYSTEM_PROMPT,
    MockProvider,
    ReadTool,
    SUBAGENT_PARENT_PROMPT_SECTION,
    SimpleAgent,
    StopReason,
    SubagentTool,
    ToolSet,
    WriteTool,
    render_subagent_prompt_section,
)
from mini_claw_code_py.types import AssistantTurn, Message, ToolCall, ToolDefinition


class RecordingProvider:
    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self._responses = responses
        self.calls: list[list[Message]] = []

    async def chat(
        self,
        messages: Sequence[Message],
        _tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        self.calls.append(list(messages))
        if not self._responses:
            raise RuntimeError("RecordingProvider: no more responses")
        return self._responses.popleft()


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


@pytest.mark.asyncio
async def test_ch13_subagent_multi_step(tmp_path: Path) -> None:
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_text("alpha")
    path_b.write_text("beta")
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="read", arguments={"path": str(path_a)})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c2", name="read", arguments={"path": str(path_b)})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="alpha and beta",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    tool = SubagentTool(provider, lambda: ToolSet().with_tool(ReadTool()))
    assert await tool.call({"task": "Read both files"}) == "alpha and beta"


@pytest.mark.asyncio
async def test_ch13_max_turns_exceeded() -> None:
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "/dev/null"})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c2", name="read", arguments={"path": "/dev/null"})],
                    stop_reason=StopReason.TOOL_USE,
                ),
            ]
        )
    )
    tool = SubagentTool(provider, lambda: ToolSet().with_tool(ReadTool())).max_turns(1)
    assert await tool.call({"task": "Loop forever"}) == "error: max turns exceeded"


@pytest.mark.asyncio
async def test_ch13_subagent_missing_task() -> None:
    provider = MockProvider(deque())
    tool = SubagentTool(provider, lambda: ToolSet())

    with pytest.raises(ValueError, match="missing required parameter: task"):
        await tool.call({})


@pytest.mark.asyncio
async def test_ch13_subagent_child_provider_error() -> None:
    provider = MockProvider(deque())
    tool = SubagentTool(provider, lambda: ToolSet())

    with pytest.raises(RuntimeError, match="MockProvider: no more responses"):
        await tool.call({"task": "Do something"})


@pytest.mark.asyncio
async def test_ch13_subagent_unknown_tool_in_child() -> None:
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="nonexistent", arguments={})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Tool not found, but I can still answer.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    tool = SubagentTool(provider, lambda: ToolSet())
    assert await tool.call({"task": "Try unknown"}) == "Tool not found, but I can still answer."


@pytest.mark.asyncio
async def test_ch13_system_prompt_in_child() -> None:
    provider = RecordingProvider(
        deque([AssistantTurn(text="Audited.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    tool = SubagentTool(provider, lambda: ToolSet()).system_prompt("You are a security auditor.")

    result = await tool.call({"task": "Audit this code"})

    assert result == "Audited."
    assert provider.calls[0][0].kind == "system"
    assert provider.calls[0][0].content == "You are a security auditor."
    assert provider.calls[0][1].kind == "user"
    assert provider.calls[0][1].content == "Audit this code"


@pytest.mark.asyncio
async def test_ch13_default_system_prompt_in_child() -> None:
    provider = RecordingProvider(
        deque([AssistantTurn(text="Done.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    tool = SubagentTool(provider, lambda: ToolSet())

    result = await tool.call({"task": "Handle this task"})

    assert result == "Done."
    assert provider.calls[0][0].kind == "system"
    assert provider.calls[0][0].content == DEFAULT_SUBAGENT_SYSTEM_PROMPT


def test_ch13_builder_pattern() -> None:
    provider = MockProvider(deque())
    tool = SubagentTool(provider, lambda: ToolSet().with_tool(ReadTool())).max_turns(5)
    assert tool.definition.name == "subagent"


def test_ch13_invalid_max_turns() -> None:
    provider = MockProvider(deque())
    with pytest.raises(ValueError, match="at least 1"):
        SubagentTool(provider, lambda: ToolSet()).max_turns(0)


def test_ch13_parent_prompt_section() -> None:
    assert render_subagent_prompt_section() == SUBAGENT_PARENT_PROMPT_SECTION
    assert "<subagent_system>" in SUBAGENT_PARENT_PROMPT_SECTION
    assert "Do not use `subagent` when" in SUBAGENT_PARENT_PROMPT_SECTION


@pytest.mark.asyncio
async def test_ch13_parent_continues_after_subagent(tmp_path: Path) -> None:
    path = tmp_path / "child.txt"
    provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="p1", name="subagent", arguments={"task": "Write a file"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write",
                            arguments={"path": str(path), "content": "from child"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Child finished writing the file.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text="Parent resumed after child: success",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = SimpleAgent(provider).tool(
        SubagentTool(provider, lambda: ToolSet().with_tool(WriteTool()))
    )

    result = await agent.run("Use a subagent to write the file")

    assert result == "Parent resumed after child: success"
    assert path.read_text() == "from child"


@pytest.mark.asyncio
async def test_ch13_child_history_does_not_leak_to_parent() -> None:
    provider = RecordingProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="p1", name="subagent", arguments={"task": "Do the delegated task"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Child summary",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text="Parent final answer",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = SimpleAgent(provider).tool(SubagentTool(provider, lambda: ToolSet()))
    history = [Message.user("Handle this with a child")]

    result = await agent.chat(history)

    assert result == "Parent final answer"
    assert len(history) == 4
    assert history[0].kind == "user"
    assert history[1].kind == "assistant"
    assert history[2].kind == "tool_result"
    assert history[2].content == "Child summary"
    assert history[3].kind == "assistant"
