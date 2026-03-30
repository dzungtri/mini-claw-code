import asyncio
from collections import deque
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import RichLog, Static

from mini_claw_code_py import (
    GoalStore,
    Message,
    MockStreamProvider,
    RunStore,
    SessionWorkStore,
    SessionStore,
    SessionRouter,
    StopReason,
    SubagentProfileRegistry,
    TaskStore,
    ToolCall,
    default_route_store,
)
from mini_claw_code_py.types import AssistantTurn
from mini_claw_code_py.tui import (
    ConsoleUI,
    WorkApp,
    resolve_option_answer,
    resolve_session_selection,
    summarize_tool_call,
)
from mini_claw_code_py.tui.console import summarize_history_message
from mini_claw_code_py.tui.app import _handle_command, build_agent


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
    assert "/channels" in rendered
    assert "/teams" in rendered
    assert "/skills" in rendered
    assert "/skill search <query>" in rendered
    assert "/work" in rendered
    assert "/goals" in rendered
    assert "/tasks" in rendered
    assert "/routes" in rendered
    assert "/runs" in rendered
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
    runs = RunStore(tmp_path / ".mini-claw" / "os")
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
            runs=runs,
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
    runs = RunStore(tmp_path / ".mini-claw" / "os")
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
            runs=runs,
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
    runs = RunStore(tmp_path / ".mini-claw" / "os")
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
            runs=runs,
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


def test_tui_handle_command_channels_prints_channel_registry(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    (tmp_path / ".channels.json").write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "telegram": {\n'
            '      "description": "Telegram front door.",\n'
            '      "default_target_agent": "superagent",\n'
            '      "thread_prefix": "tg"\n'
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
            prompt="/channels",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
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
    assert "Channels" in rendered
    assert "cli" in rendered
    assert "telegram" in rendered


def test_tui_handle_command_skills_prints_skill_summary(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    skill_root = tmp_path / ".agents" / "skills" / "calendar-helper"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        (
            "---\n"
            "name: calendar-helper\n"
            "description: Calendar workflow helper.\n"
            "---\n"
            "\n"
            "Use this skill for calendar workflows.\n"
        ),
        encoding="utf-8",
    )

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/skills",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
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
    assert "Skills" in rendered
    assert "calendar-helper" in rendered


def test_tui_handle_command_skill_search_renders_hub_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    class FakeManager:
        def search(self, query: str) -> object:
            class Result:
                stdout = f"Found remote skill for: {query}"

            return Result()

    monkeypatch.setattr("mini_claw_code_py.tui.app._skill_hub_manager", lambda workspace: FakeManager())

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/skill search postgres backups",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
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
    assert "Skill Search" in rendered
    assert "postgres backups" in rendered


def test_tui_handle_command_routes_prints_route_store(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.persist(store.create(cwd=tmp_path))
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/routes",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
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
    assert "Routes" in rendered
    assert "cli:local" in rendered
    assert current_session.id in rendered


def test_tui_handle_command_runs_prints_run_store(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.persist(store.create(cwd=tmp_path))
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    run = runs.start(
        task_id=None,
        agent_name="superagent",
        source="cli",
        thread_key="cli:local",
        session_id=current_session.id,
        trace_id="trace_demo",
    )
    runs.finish(run.run_id, status="completed")

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    async def run_command() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/runs",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            agent=DummyAgent(),  # type: ignore[arg-type]
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run_command())

    rendered = console.export_text()
    assert handled is True
    assert "Runs" in rendered


def test_tui_handle_command_work_prints_session_binding(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    goals = GoalStore(tmp_path / ".mini-claw" / "os")
    tasks = TaskStore(tmp_path / ".mini-claw" / "os")
    session_work = SessionWorkStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    goal = goals.create(title="Release", description="Ship it.", primary_team="default")
    task = tasks.assign(goal_id=goal.goal_id, team_id="default", agent_name="superagent", title="Drive the release")
    session_work.bind(session_id=current_session.id, goal_id=goal.goal_id, task_id=task.task_id, team_id="default")

    class DummyAgent:
        def subagent_profile_registry(self) -> SubagentProfileRegistry:
            return SubagentProfileRegistry({})

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/work",
            provider=None,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            goals=goals,
            tasks=tasks,
            session_work=session_work,
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
    assert "Work" in rendered
    assert goal.goal_id in rendered
    assert task.task_id in rendered


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


def _build_work_app(tmp_path: Path, turns: deque[AssistantTurn]) -> WorkApp:
    (tmp_path / "home").mkdir(exist_ok=True)
    provider = MockStreamProvider(turns)
    return WorkApp(provider=provider, cwd=tmp_path, home=tmp_path / "home")


async def _pause_twice(pilot: object) -> None:
    await pilot.pause()
    await pilot.pause()


async def _press_text(pilot: object, text: str) -> None:
    keys = [character if character != " " else "space" for character in text]
    if keys:
        await pilot.press(*keys)


async def _transcript_text(app: WorkApp) -> str:
    transcript = app.query_one("#transcript", RichLog)
    rendered_lines: list[str] = []
    for line in transcript.lines:
        segments = getattr(line, "_segments", None) or getattr(line, "segments", None)
        if segments is None:
            rendered_lines.append(str(line))
            continue
        rendered_lines.append("".join(segment.text for segment in segments))
    return "\n".join(rendered_lines)


@pytest.mark.asyncio
async def test_tui_work_app_mounts_and_renders_session_summary(tmp_path: Path) -> None:
    app = _build_work_app(tmp_path, deque())

    async with app.run_test() as pilot:
        await _pause_twice(pilot)
        summary = app.query_one("#summary", Static)
        sidebar = app.query_one("#sidebar", Static)

        assert "mode=execution" in str(summary.content)
        assert "session=" in str(summary.content)
        assert "work=no active binding" in str(sidebar.content)


@pytest.mark.asyncio
async def test_tui_work_app_executes_prompt_and_updates_history_and_runs(tmp_path: Path) -> None:
    app = _build_work_app(
        tmp_path,
        deque([AssistantTurn(text="Hello from work app.", tool_calls=[], stop_reason=StopReason.STOP)]),
    )

    async with app.run_test() as pilot:
        await _pause_twice(pilot)
        await _press_text(pilot, "Hello")
        await pilot.press("enter")
        await _pause_twice(pilot)
        await _pause_twice(pilot)

        summary = app.query_one("#summary", Static)
        transcript_text = await _transcript_text(app)
        runs = RunStore(tmp_path / ".mini-claw" / "os").list()

        assert "run_state=idle" in str(summary.content)
        assert app.history[-1].turn is not None
        assert app.history[-1].turn.text == "Hello from work app."
        assert any(run.status == "completed" for run in runs)
        assert "Hello from work app." in transcript_text


@pytest.mark.asyncio
async def test_tui_work_app_handles_slash_commands_in_textual_console(tmp_path: Path) -> None:
    app = _build_work_app(tmp_path, deque())

    async with app.run_test() as pilot:
        await _pause_twice(pilot)
        await pilot.press("/", "p", "l", "a", "n", "enter")
        await _pause_twice(pilot)
        await pilot.press("/", "s", "t", "a", "t", "u", "s", "enter")
        await _pause_twice(pilot)

        summary = app.query_one("#summary", Static)
        transcript_text = await _transcript_text(app)

        assert "mode=planning" in str(summary.content)
        assert "planning ON" in transcript_text
        assert "Control profile:" in transcript_text


def test_tui_handle_command_agent_add_writes_project_registry(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    provider = MockStreamProvider(deque())
    agent = build_agent(provider, cwd=tmp_path, input_queue=asyncio.Queue())

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt='/agent add reviewer --workspace . --description "Review repository changes."',
            provider=provider,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run())

    rendered = console.export_text()
    assert handled is True
    assert "Agent Added" in rendered
    assert '"reviewer"' in (tmp_path / ".agents.json").read_text(encoding="utf-8")


def test_tui_handle_command_team_and_channel_add_write_project_config(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    provider = MockStreamProvider(deque())
    agent = build_agent(provider, cwd=tmp_path, input_queue=asyncio.Queue())
    (tmp_path / ".agents.json").write_text(
        (
            '{\n'
            '  "agents": {\n'
            '    "support-lead": {\n'
            '      "description": "Support lead.",\n'
            '      "workspace_root": ".",\n'
            '      "default_channels": ["cli"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    async def run_team() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt='/team add support --lead support-lead --member support-lead --description "Support team."',
            provider=provider,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run_team())
    assert handled is True
    assert '"support"' in (tmp_path / ".teams.json").read_text(encoding="utf-8")

    async def run_channel() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt='/channel add telegram --team support --prefix tg --description "Telegram front door."',
            provider=provider,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run_channel())
    rendered = console.export_text()
    assert handled is True
    assert "Channel Added" in rendered
    assert '"telegram"' in (tmp_path / ".channels.json").read_text(encoding="utf-8")


def test_tui_handle_command_mcp_add_writes_project_config(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    provider = MockStreamProvider(deque())
    agent = build_agent(provider, cwd=tmp_path, input_queue=asyncio.Queue())

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/mcp add stdio filesystem-demo uvx mcp-server-filesystem .",
            provider=provider,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, _, _, _, _ = asyncio.run(run())

    rendered = console.export_text()
    assert handled is True
    assert "MCP Added" in rendered
    assert '"filesystem-demo"' in (tmp_path / ".mcp.json").read_text(encoding="utf-8")


def test_tui_handle_command_use_channel_switches_active_route(tmp_path: Path) -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    runs = RunStore(tmp_path / ".mini-claw" / "os")
    router = SessionRouter(default_route_store(tmp_path), store)
    current_session = store.create(cwd=tmp_path)
    current_route = router.bind(target_agent="superagent", thread_key="cli:local", session_id=current_session.id)
    provider = MockStreamProvider(deque())
    agent = build_agent(provider, cwd=tmp_path, input_queue=asyncio.Queue())
    (tmp_path / ".agents.json").write_text(
        (
            '{\n'
            '  "agents": {\n'
            '    "support-lead": {\n'
            '      "description": "Support lead.",\n'
            '      "workspace_root": ".",\n'
            '      "default_channels": ["cli", "telegram"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".teams.json").write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "support": {\n'
            '      "description": "Support team.",\n'
            '      "lead_agent": "support-lead",\n'
            '      "member_agents": ["support-lead"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".channels.json").write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "telegram": {\n'
            '      "description": "Telegram front door.",\n'
            '      "default_team": "support",\n'
            '      "thread_prefix": "tg"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    async def run() -> tuple[bool, object, object, object, list[Message], bool]:
        return await _handle_command(
            prompt="/use channel telegram",
            provider=provider,  # type: ignore[arg-type]
            workspace=tmp_path,
            input_queue=asyncio.Queue(),
            store=store,
            router=router,
            runs=runs,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=[],
            plan_mode=False,
            ui=ui,
        )

    handled, _, new_route, new_session, _, _ = asyncio.run(run())

    rendered = console.export_text()
    assert handled is True
    assert "Route Updated" in rendered
    assert new_route.target_agent == "support-lead"
    assert new_route.thread_key == "tg:local"
    assert new_session.id
