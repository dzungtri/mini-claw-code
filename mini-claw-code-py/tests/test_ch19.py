import asyncio
from collections import deque

import pytest

from mini_claw_code_py import (
    ARCHIVED_CONTEXT_OPEN,
    AgentNotice,
    ContextCompactionSettings,
    HarnessAgent,
    Message,
    MockStreamProvider,
    StopReason,
    ToolCall,
    compact_message_history,
    estimate_messages_tokens,
    render_context_durability_prompt_section,
)
from mini_claw_code_py.types import AssistantTurn


def test_ch19_compact_message_history_inserts_archived_summary() -> None:
    messages = [
        Message.system("System prompt"),
        Message.user("Investigate the auth bug"),
        Message.assistant(
            AssistantTurn(
                text=None,
                tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "auth.py"})],
                stop_reason=StopReason.TOOL_USE,
            )
        ),
        Message.tool_result("c1", "auth.py contents"),
        Message.user("Now inspect tests"),
        Message.assistant(
            AssistantTurn(
                text="I found one failing test.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
        Message.user("Patch it"),
    ]

    result = compact_message_history(
        messages,
        ContextCompactionSettings(max_messages=4, keep_recent=2),
    )

    assert result is not None
    assert result.archived_messages == 4
    assert messages[0].kind == "system"
    assert messages[1].kind == "system"
    assert messages[1].content is not None
    assert messages[1].content.startswith(ARCHIVED_CONTEXT_OPEN)
    assert "Investigate the auth bug" in messages[1].content
    assert "used tools: `read`" in messages[1].content
    assert messages[-2].content == "Patch it" or messages[-1].content == "Patch it"


def test_ch19_compaction_merges_existing_archive() -> None:
    messages = [
        Message.system("System prompt"),
        Message.system(
            """<archived_context>
Older conversation history was compacted to preserve continuity.
Use this summary as durable archived context.

Assistant conclusions:
- Earlier archive summary.

Prefer the recent live messages for immediate detail and use this archive for continuity.
</archived_context>"""
        ),
        Message.user("Research another file"),
        Message.assistant(
            AssistantTurn(
                text=None,
                tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "b.py"})],
                stop_reason=StopReason.TOOL_USE,
            )
        ),
        Message.tool_result("c1", "b.py contents"),
        Message.user("Continue"),
    ]

    result = compact_message_history(
        messages,
        ContextCompactionSettings(max_messages=3, keep_recent=2),
    )

    assert result is not None
    assert messages[1].content is not None
    assert "Earlier archived context" in messages[1].content
    assert "Earlier archive summary." in messages[1].content


def test_ch19_render_context_durability_prompt_section() -> None:
    section = render_context_durability_prompt_section()

    assert "<context_durability>" in section
    assert "archived context summary" in section
    assert "estimated token budget" in section


def test_ch19_compaction_can_trigger_from_estimated_tokens() -> None:
    messages = [
        Message.system("System prompt"),
        Message.user("A" * 240),
        Message.assistant(
            AssistantTurn(
                text="B" * 240,
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
        Message.user("Keep this recent request"),
    ]

    active_tokens_before = estimate_messages_tokens(messages[1:])
    result = compact_message_history(
        messages,
        ContextCompactionSettings(
            max_messages=10,
            keep_recent=2,
            max_estimated_tokens=80,
        ),
    )

    assert result is not None
    assert active_tokens_before > 80
    assert "estimated_tokens" in result.triggered_by
    assert result.estimated_tokens_before == active_tokens_before
    assert result.estimated_tokens_after < result.estimated_tokens_before


@pytest.mark.asyncio
async def test_ch19_harness_emits_compaction_notice_and_keeps_archive() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "pyproject.toml"})],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Done with long task.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_context_durability(max_messages=4, keep_recent=2)
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [
        Message.user("Step 1"),
        Message.assistant(
            AssistantTurn(
                text="Observed one issue.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
        Message.user("Step 2"),
        Message.assistant(
            AssistantTurn(
                text="Observed a second issue.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
        Message.user("Step 3"),
    ]

    result = await agent.execute(messages, queue)

    assert result == "Done with long task."
    archived = [message for message in messages if message.kind == "system" and message.content]
    assert any(message.content and message.content.startswith(ARCHIVED_CONTEXT_OPEN) for message in archived[1:])

    notices = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)

    assert any(message.startswith("Context compacted:") for message in notices)
    assert any("estimated tokens" in message for message in notices)
