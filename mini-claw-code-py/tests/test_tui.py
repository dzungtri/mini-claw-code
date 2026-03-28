import asyncio
from pathlib import Path

from rich.console import Console

from mini_claw_code_py import (
    Message,
    SessionStore,
    SessionRouter,
    StopReason,
    SubagentProfileRegistry,
    ToolCall,
    default_route_store,
)
from mini_claw_code_py.types import AssistantTurn
from mini_claw_code_py.tui import (
    ConsoleUI,
    resolve_option_answer,
    resolve_session_selection,
    summarize_tool_call,
)
from mini_claw_code_py.tui.console import summarize_history_message
from mini_claw_code_py.tui.app import _handle_command


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
    assert "/artifacts" in rendered
    assert "/mcp" in rendered
    assert "/subagents" in rendered
    assert "/agents" in rendered
    assert "/teams" in rendered
    assert "/fork" in rendered
    assert "/rename <title>" in rendered
    assert "/resume <id>" in rendered
    assert "/sessions" in rendered


def test_tui_print_subagents_renders_profile_registry() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry.discover(
                [
                    Path("/tmp/does-not-exist"),
                ]
            )

    ui.print_subagents(DummyAgent())

    rendered = console.export_text()
    assert "Subagents" in rendered
    assert "Subagent profiles: none." in rendered


def test_tui_print_subagents_renders_loaded_profile_details(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    config_path = tmp_path / ".subagents.json"
    config_path.write_text(
        (
            '{\n'
            '  "subagents": {\n'
            '    "packaging-helper": {\n'
            '      "description": "Use for packaging tasks.",\n'
            '      "skills": ["python-packaging"],\n'
            '      "tools": ["read", "bash"],\n'
            '      "max_turns": 6\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry.discover([config_path])

    ui.print_subagents(DummyAgent())

    rendered = console.export_text()
    assert "packaging-helper" in rendered
    assert "python-packaging" in rendered
    assert "read, bash" in rendered
    assert "6" in rendered


def test_tui_handle_command_subagents_prints_registry(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry(
                {
                    "packaging-helper": next(
                        iter(
                            SubagentProfileRegistry.discover(
                                [
                                    _write_temp_subagent_config(tmp_path),
                                ]
                            ).all()
                        )
                    )
                }
            )

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/subagents",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            agent=DummyAgent(),  # type: ignore[arg-type]
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run())

    rendered = console.export_text()
    assert handled is True
    assert "Subagents" in rendered
    assert "packaging-helper" in rendered


def test_tui_handle_command_agents_prints_hosted_registry(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    (tmp_path / ".agents.json").write_text(
        (
            '{\n'
            '  "agents": {\n'
            '    "reviewer": {\n'
            '      "description": "Review repository changes.",\n'
            '      "workspace_root": ".",\n'
            '      "default_channels": ["cli"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/agents",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            agent=DummyAgent(),  # type: ignore[arg-type]
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run())

    rendered = console.export_text()
    assert handled is True
    assert "Hosted Agents" in rendered
    assert "superagent" in rendered
    assert "reviewer" in rendered


def test_tui_handle_command_teams_prints_team_registry(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    (tmp_path / ".teams.json").write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "product-a": {\n'
            '      "description": "Project delivery team.",\n'
            '      "lead_agent": "superagent",\n'
            '      "member_agents": ["backend-dev", "frontend-dev"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/teams",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            agent=DummyAgent(),  # type: ignore[arg-type]
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run())

    rendered = console.export_text()
    assert handled is True
    assert "Teams" in rendered
    assert "default" in rendered
    assert "product-a" in rendered


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


def _write_temp_subagent_config(root: Path) -> Path:
    config_path = root / ".subagents.json"
    config_path.write_text(
        (
            '{\n'
            '  "subagents": {\n'
            '    "packaging-helper": {\n'
            '      "description": "Use for packaging tasks.",\n'
            '      "skills": ["python-packaging"],\n'
            '      "tools": ["read", "bash"],\n'
            '      "max_turns": 6\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    return config_path
