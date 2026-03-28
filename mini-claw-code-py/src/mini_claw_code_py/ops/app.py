from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.widgets import Footer, Header, Input, Static

from mini_claw_code_py import OperatorService


class OperatorApp(App[None]):
    TITLE = "AgentOS Ops"
    SUB_TITLE = "monitoring and administration"
    CSS = """
    Screen {
        layout: vertical;
    }

    #dashboard {
        height: 1fr;
        layout: vertical;
    }

    #summary {
        height: auto;
        border: round $accent;
        padding: 0 1;
        margin: 0 1;
    }

    #grid {
        height: 1fr;
        grid-size: 2 3;
        grid-rows: 1fr 1fr 1fr;
        grid-columns: 1fr 1fr;
        margin: 0 1;
    }

    .panel {
        border: round $panel;
        padding: 0 1;
        content-align: left top;
    }

    #detail {
        height: 1fr;
        border: round $warning;
        margin: 0 1;
        padding: 0 1;
    }

    #command {
        dock: bottom;
        margin: 0 1 1 1;
    }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "refresh_snapshot", "Refresh"),
        Binding("/", "focus_command", "Command"),
        Binding("escape", "clear_detail", "Back"),
    ]

    def __init__(self, service: OperatorService) -> None:
        super().__init__()
        self.service = service
        self._detail_mode = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="dashboard"):
            yield Static(id="summary")
            with Grid(id="grid"):
                yield Static(id="teams", classes="panel")
                yield Static(id="runs", classes="panel")
                yield Static(id="agents", classes="panel")
                yield Static(id="routes", classes="panel")
                yield Static(id="sessions", classes="panel")
                yield Static(id="alerts", classes="panel")
            yield Static(id="detail", classes="panel")
        yield Input(placeholder="Type /help, /inspect run <id>, /back, /refresh", id="command")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#detail", Static).display = False
        self.refresh_snapshot()
        self.query_one("#command", Input).focus()
        self.set_interval(1.0, self.refresh_snapshot)

    def action_focus_command(self) -> None:
        self.query_one("#command", Input).focus()

    def action_refresh_snapshot(self) -> None:
        self.refresh_snapshot()

    def action_clear_detail(self) -> None:
        self._detail_mode = False
        detail = self.query_one("#detail", Static)
        detail.display = False
        detail.update("")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if not command:
            return
        if command in {"/help", ":help"}:
            self._show_detail(_help_text())
            return
        if command in {"/back", ":back"}:
            self.action_clear_detail()
            return
        if command in {"/refresh", ":refresh"}:
            self.refresh_snapshot()
            return
        if command.startswith("/inspect run ") or command.startswith(":inspect run "):
            run_id = command.split(maxsplit=2)[2].strip()
            self.inspect_run(run_id)
            return
        if command.startswith("/cancel run ") or command.startswith(":cancel run "):
            run_id = command.split(maxsplit=2)[2].strip()
            self._show_detail(self.service.cancel_run(run_id))
            self.refresh_snapshot()
            return
        self._show_detail(f"Unknown command: {command}\n\nTry /help.")

    def inspect_run(self, run_id: str) -> None:
        run = self.service.inspect_run(run_id)
        if run is None:
            self._show_detail(f"Run not found: {run_id}")
            return
        lines = [
            f"Inspect Run: {run.run_id}",
            "",
            f"status={run.status}",
            f"agent={run.agent_name}",
            f"source={run.source}",
            f"thread={run.thread_key}",
            f"session={run.session_id}",
            f"trace={run.trace_id}",
        ]
        if run.task_id:
            lines.append(f"task={run.task_id}")
        lines.extend(
            [
                "",
                "Usage",
                f"turns={run.turn_count}",
                f"tool_calls={run.tool_call_count}",
                f"subagents={run.subagent_count}",
                f"prompt_tokens={run.prompt_tokens}",
                f"completion_tokens={run.completion_tokens}",
                f"total_tokens={run.total_tokens}",
                f"estimated_input_cost=${run.estimated_input_cost_usd:.6f}",
                f"estimated_output_cost=${run.estimated_output_cost_usd:.6f}",
                f"estimated_total_cost=${run.estimated_total_cost_usd:.6f}",
                f"context_pressure={run.context_pressure_percent}%",
            ]
        )
        if run.pricing_key:
            lines.append(f"pricing_key={run.pricing_key}")
        if run.provider_name or run.model_name:
            lines.append(f"provider={run.provider_name} model={run.model_name}")
        self._show_detail("\n".join(lines))

    def refresh_snapshot(self) -> None:
        snapshot = self.service.snapshot()
        self.query_one("#summary", Static).update(_render_summary(snapshot))
        self.query_one("#teams", Static).update(_render_teams(snapshot))
        self.query_one("#runs", Static).update(_render_runs(snapshot))
        self.query_one("#agents", Static).update(_render_agents(snapshot))
        self.query_one("#routes", Static).update(_render_routes(snapshot))
        self.query_one("#sessions", Static).update(_render_sessions(snapshot))
        self.query_one("#alerts", Static).update(_render_alerts(snapshot))

    def _show_detail(self, text: str) -> None:
        self._detail_mode = True
        detail = self.query_one("#detail", Static)
        detail.display = True
        detail.update(text)


def run_ops(*, cwd: Path | None = None) -> None:
    service = OperatorService.discover_default(cwd=Path.cwd() if cwd is None else cwd, home=Path.home())
    OperatorApp(service).run()


def _render_summary(snapshot: object) -> str:
    summary = snapshot.summary
    return (
        "AgentOS Ops\n"
        f"active_runs={summary.active_runs}  "
        f"completed_runs={summary.completed_runs}  "
        f"failed_runs={summary.failed_runs}  "
        f"tokens={summary.total_tokens}  "
        f"est_cost=${summary.estimated_total_cost_usd:.6f}"
    )


def _render_teams(snapshot: object) -> str:
    lines = ["Teams"]
    for team in snapshot.teams:
        lines.append(
            f"- {team.name}: active={team.active_runs} tokens={team.total_tokens} cost=${team.estimated_total_cost_usd:.6f}"
        )
    return "\n".join(lines)


def _render_runs(snapshot: object) -> str:
    lines = ["Runs"]
    for run in snapshot.runs[:10]:
        lines.append(
            f"- {run.run_id}: {run.agent_name} {run.status} tokens={run.total_tokens} cost=${run.estimated_total_cost_usd:.6f} ctx={run.context_pressure_percent}%"
        )
    return "\n".join(lines)


def _render_agents(snapshot: object) -> str:
    lines = ["Agents"]
    for agent in snapshot.agents:
        lines.append(
            f"- {agent.name}: {agent.state} runs={agent.active_runs} tokens={agent.total_tokens} cost=${agent.estimated_total_cost_usd:.6f}"
        )
    return "\n".join(lines)


def _render_routes(snapshot: object) -> str:
    lines = ["Routes"]
    for route in snapshot.routes[:10]:
        lines.append(f"- {route.target_agent} + {route.thread_key} -> {route.session_id}")
    return "\n".join(lines)


def _render_sessions(snapshot: object) -> str:
    lines = ["Sessions"]
    for session in snapshot.sessions[:10]:
        lines.append(f"- {session.id}: {session.title}")
    return "\n".join(lines)


def _render_alerts(snapshot: object) -> str:
    lines = ["Alerts"]
    alerts: list[str] = []
    for run in snapshot.runs:
        if run.status == "failed":
            alerts.append(f"FAIL {run.run_id} {run.agent_name}")
        elif run.context_pressure_percent >= 85:
            alerts.append(f"WARN {run.run_id} context={run.context_pressure_percent}%")
    if not alerts:
        alerts.append("No alerts.")
    lines.extend(alerts[:10])
    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "Commands",
            "",
            "/help",
            "/refresh",
            "/inspect run <id>",
            "/cancel run <id>",
            "/back",
        ]
    )
