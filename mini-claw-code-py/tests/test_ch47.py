import asyncio
from collections import deque
from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from mini_claw_code_py import (
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageEnvelope,
    MockStreamProvider,
    OperatorService,
    RunStore,
    SessionRouter,
    SessionStore,
    StopReason,
    TeamRegistry,
    TurnRunner,
    default_os_state_root,
    default_route_store,
)
from mini_claw_code_py.ops.app import OperatorApp
from mini_claw_code_py.tools import UserInputRequest
from mini_claw_code_py.types import AssistantTurn


def _build_runner(root: Path) -> TurnRunner:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="Hello.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    sessions = SessionStore(root / ".mini-claw" / "sessions")
    return TurnRunner(
        registry=HostedAgentRegistry.discover_default(cwd=root, home=root / "home"),
        factory=HostedAgentFactory(
            provider=provider,  # type: ignore[arg-type]
            home=root / "home",
            input_queue=input_queue,
        ),
        router=SessionRouter(default_route_store(root), sessions),
        sessions=sessions,
        runs=RunStore(default_os_state_root(root)),
    )


def test_ch47_operator_service_snapshot_aggregates_routes_runs_agents_and_costs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("MINI_CLAW_INPUT_COST_PER_MILLION_USD", "3")
    monkeypatch.setenv("MINI_CLAW_OUTPUT_COST_PER_MILLION_USD", "5")
    runner = _build_runner(tmp_path)
    asyncio.run(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="Hello",
            )
        )
    )

    service = OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home")
    snapshot = service.snapshot()

    assert snapshot.summary.completed_runs >= 1
    assert snapshot.summary.total_tokens > 0
    assert snapshot.summary.estimated_total_cost_usd > 0
    assert any(route.thread_key == "cli:local" for route in snapshot.routes)
    assert any(agent.name == "superagent" for agent in snapshot.agents)
    assert any(team.name == "default" for team in snapshot.teams)


@pytest.mark.asyncio
async def test_ch47_operator_app_renders_dashboard_and_inspects_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("MINI_CLAW_INPUT_COST_PER_MILLION_USD", "3")
    monkeypatch.setenv("MINI_CLAW_OUTPUT_COST_PER_MILLION_USD", "5")
    runner = _build_runner(tmp_path)
    result = await runner.run(
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="Hello",
        )
    )

    app = OperatorApp(OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home"))

    async with app.run_test() as pilot:
        await pilot.pause()
        summary = app.query_one("#summary", Static)
        runs = app.query_one("#runs", DataTable)
        assert "AgentOS Ops" in str(summary.content)
        assert runs.row_count >= 1

        await pilot.press("enter")
        await pilot.pause()

        detail = app.query_one("#detail", Static)
        assert detail.display is True
        assert result.context.run.run_id in str(detail.content)
        assert "estimated_total_cost" in str(detail.content)


@pytest.mark.asyncio
async def test_ch47_operator_app_command_input_accepts_spaces(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("MINI_CLAW_INPUT_COST_PER_MILLION_USD", "3")
    monkeypatch.setenv("MINI_CLAW_OUTPUT_COST_PER_MILLION_USD", "5")
    runner = _build_runner(tmp_path)
    result = await runner.run(
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="Hello",
        )
    )

    app = OperatorApp(OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home"))

    async with app.run_test() as pilot:
        await pilot.pause()
        runs = app.query_one("#runs", DataTable)
        assert runs.has_focus
        await pilot.press("/", "i", "n", "s", "p", "e", "c", "t", "space", "r", "u", "n", "space")
        await pilot.pause()
        command = app.query_one("#command")
        assert command.value == "inspect run "

        await pilot.press(*result.context.run.run_id, "enter")
        await pilot.pause()

        detail = app.query_one("#detail", Static)
        assert result.context.run.run_id in str(detail.content)


@pytest.mark.asyncio
async def test_ch47_operator_app_can_copy_selected_run_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    runner = _build_runner(tmp_path)
    result = await runner.run(
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="Hello",
        )
    )

    copied: list[str] = []

    app = OperatorApp(OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home"))
    monkeypatch.setattr(app, "copy_to_clipboard", lambda text: copied.append(text))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+y")
        await pilot.pause()

    assert copied == [result.context.run.run_id]


@pytest.mark.asyncio
async def test_ch47_operator_app_can_inspect_session_from_table(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    runner = _build_runner(tmp_path)
    result = await runner.run(
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="Hello",
        )
    )

    app = OperatorApp(OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home"))

    async with app.run_test() as pilot:
        await pilot.pause()
        sessions = app.query_one("#sessions", DataTable)
        sessions.focus()
        await pilot.pause()
        assert sessions.has_focus

        await pilot.press("enter")
        await pilot.pause()

        detail = app.query_one("#detail", Static)
        assert result.context.run.session_id in str(detail.content)
        assert "Inspect Session" in str(detail.content)


@pytest.mark.asyncio
async def test_ch47_operator_app_supports_quit_command(
    tmp_path: Path,
) -> None:
    (tmp_path / "home").mkdir()
    runner = _build_runner(tmp_path)
    await runner.run(
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="Hello",
        )
    )

    app = OperatorApp(OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home"))
    called = {"quit": False}

    def _mark_quit() -> None:
        called["quit"] = True

    app.action_request_quit = _mark_quit  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/", "q", "u", "i", "t", "enter")
        await pilot.pause()

    assert called["quit"] is True
