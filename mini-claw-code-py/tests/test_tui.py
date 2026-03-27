from rich.console import Console

from mini_claw_code_py.tui import (
    ConsoleUI,
    resolve_option_answer,
    resolve_session_selection,
    summarize_tool_call,
)


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
