from rich.console import Console

from mini_claw_code_py import Message, StopReason, ToolCall
from mini_claw_code_py.types import AssistantTurn
from mini_claw_code_py.tui import (
    ConsoleUI,
    resolve_option_answer,
    resolve_session_selection,
    summarize_tool_call,
)
from mini_claw_code_py.tui.console import summarize_history_message


def test_tui_resolve_option_answer_accepts_numeric_choice() -> None:
    assert resolve_option_answer("2", ["yes", "no", "later"]) == "no"
    assert resolve_option_answer(" custom ", ["yes", "no"]) == "custom"


def test_tui_resolve_session_selection_accepts_number_and_id() -> None:
    session_ids = ["sess_a", "sess_b", "sess_c"]

    assert resolve_session_selection("2", session_ids) == "sess_b"
    assert resolve_session_selection("sess_c", session_ids) == "sess_c"
    assert resolve_session_selection("   ", session_ids) is None


def test_tui_summarize_tool_call_collapses_after_threshold() -> None:
    shown = summarize_tool_call(
        tool_count=2,
        summary="read README.md",
        name="read",
        collapse_after=3,
        always_show=set(),
        collapsed_tools_reported=False,
    )
    collapsed = summarize_tool_call(
        tool_count=5,
        summary="grep TODO",
        name="bash",
        collapse_after=3,
        always_show=set(),
        collapsed_tools_reported=False,
    )

    assert shown.show is True
    assert shown.message == "read README.md"
    assert collapsed.show is True
    assert collapsed.message == "additional tool calls omitted"


def test_tui_print_help_lists_core_commands() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    ui.print_help()

    rendered = console.export_text()
    assert "/help" in rendered
    assert "/plan" in rendered
    assert "/resume <id>" in rendered
    assert "/sessions" in rendered


def test_tui_summarize_history_message_formats_assistant_tool_calls() -> None:
    message = Message.assistant(
        AssistantTurn(
            text=None,
            tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "README.md"})],
            stop_reason=StopReason.TOOL_USE,
        )
    )

    role, text = summarize_history_message(message) or ("", "")

    assert role == "assistant"
    assert "[tool call] read" in text


def test_tui_print_history_preview_renders_recent_context_panel() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    history = [
        Message.user("Help me write a poem about rain."),
        Message.assistant(
            AssistantTurn(
                text="Sure. Do you want it short or long?",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
        Message.tool_result("c1", "Saved draft to notes.md"),
    ]

    ui.print_history_preview(history, limit=3)

    rendered = console.export_text()
    assert "Recent Context" in rendered
    assert "Help me write a poem about rain." in rendered
    assert "Sure. Do you want it short or long?" in rendered
    assert "Saved draft to notes.md" in rendered
