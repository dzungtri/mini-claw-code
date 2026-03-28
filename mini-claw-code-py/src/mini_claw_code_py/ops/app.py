from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Grid, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Static

from mini_claw_code_py import OperatorService
from mini_claw_code_py.os.operator import OperatorSnapshot
from mini_claw_code_py.os.session_router import SessionRoute
from mini_claw_code_py.os.work import RunRecord
from mini_claw_code_py.session import SessionRecord


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

    .table-panel {
        border: round $panel;
        margin: 0;
        padding: 0;
    }

    DataTable {
        height: 1fr;
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
        Binding("ctrl+q", "request_quit", "Quit"),
        Binding("ctrl+r", "refresh_snapshot", "Refresh"),
        Binding("ctrl+y", "copy_selected_id", "Copy ID"),
        Binding("/", "focus_command", "Command"),
        Binding("escape", "clear_detail", "Back"),
    ]

    def __init__(self, service: OperatorService) -> None:
        super().__init__()
        self.service = service
        self._detail_mode = False
        self._refreshing_tables = False
        self._run_row_ids: list[str] = []
        self._session_row_ids: list[str] = []
        self._route_row_keys: list[str] = []
        self._routes_by_key: dict[str, SessionRoute] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="dashboard"):
            yield Static(id="summary")
            with Grid(id="grid"):
                yield DataTable(id="teams", classes="table-panel", show_cursor=False)
                yield DataTable(id="runs", classes="table-panel", cursor_type="row")
                yield DataTable(id="agents", classes="table-panel", show_cursor=False)
                yield DataTable(id="routes", classes="table-panel", cursor_type="row")
                yield DataTable(id="sessions", classes="table-panel", cursor_type="row")
                yield Static(id="alerts", classes="panel")
            yield Static(id="detail", classes="panel")
        yield Input(
            placeholder="Type /help, /inspect run <id>, /inspect session <id>, /cancel run <id>, /quit",
            id="command",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#detail", Static).display = False
        self._configure_tables()
        self.refresh_snapshot()
        self.query_one("#runs", DataTable).focus()
        if self._run_row_ids:
            self.inspect_run(self._run_row_ids[0])
        self.set_interval(1.0, self.refresh_snapshot)

    def _configure_tables(self) -> None:
        teams = self.query_one("#teams", DataTable)
        teams.add_columns("team", "lead", "active", "tokens", "cost")

        runs = self.query_one("#runs", DataTable)
        runs.add_columns("run_id", "agent", "status", "tokens", "cost", "ctx%", "session")

        agents = self.query_one("#agents", DataTable)
        agents.add_columns("agent", "state", "runs", "tokens", "cost")

        routes = self.query_one("#routes", DataTable)
        routes.add_columns("agent", "thread", "session")

        sessions = self.query_one("#sessions", DataTable)
        sessions.add_columns("session_id", "title", "updated")

    def action_request_quit(self) -> None:
        self.exit()

    def action_focus_command(self) -> None:
        command = self.query_one("#command", Input)
        if not command.value:
            command.value = "/"
        elif not command.value.startswith(("/", ":")):
            command.value = f"/{command.value}"
        command.cursor_position = len(command.value)
        command.focus()

    def action_refresh_snapshot(self) -> None:
        self.refresh_snapshot()

    def action_copy_selected_id(self) -> None:
        selected = self._selected_identifier()
        if selected is None:
            return
        self.copy_to_clipboard(selected)
        self.notify(f"Copied: {selected}")

    def action_clear_detail(self) -> None:
        self._detail_mode = False
        detail = self.query_one("#detail", Static)
        detail.display = False
        detail.update("")
        self.query_one("#runs", DataTable).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if not command:
            return
        normalized = command[1:] if command.startswith(("/", ":")) else command
        normalized = normalized.strip()
        if normalized == "help":
            self._show_detail(_help_text())
            return
        if normalized == "back":
            self.action_clear_detail()
            return
        if normalized == "refresh":
            self.refresh_snapshot()
            return
        if normalized == "quit":
            self.action_request_quit()
            return
        if normalized.startswith("inspect run "):
            run_id = normalized.split(maxsplit=2)[2].strip()
            self.inspect_run(run_id)
            return
        if normalized.startswith("inspect session "):
            session_id = normalized.split(maxsplit=2)[2].strip()
            self.inspect_session(session_id)
            return
        if normalized.startswith("cancel run "):
            run_id = normalized.split(maxsplit=2)[2].strip()
            self._show_detail(self.service.cancel_run(run_id))
            self.refresh_snapshot()
            return
        self._show_detail(f"Unknown command: {command}\n\nTry /help.")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._refreshing_tables or self.focused is not event.data_table:
            return
        self._inspect_table_row(str(event.data_table.id), event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._refreshing_tables or self.focused is not event.data_table:
            return
        self._inspect_table_row(str(event.data_table.id), event.cursor_row)

    def inspect_run(self, run_id: str) -> None:
        run = self.service.inspect_run(run_id)
        if run is None:
            self._show_detail(f"Run not found: {run_id}")
            return
        self._show_detail(_render_run_detail(run))

    def inspect_session(self, session_id: str) -> None:
        session = self.service.inspect_session(session_id)
        if session is None:
            self._show_detail(f"Session not found: {session_id}")
            return
        self._show_detail(_render_session_detail(session))

    def inspect_route(self, route_key: str) -> None:
        route = self._routes_by_key.get(route_key)
        if route is None:
            self._show_detail(f"Route not found: {route_key}")
            return
        self._show_detail(_render_route_detail(route))

    def refresh_snapshot(self) -> None:
        snapshot = self.service.snapshot()
        try:
            summary = self.query_one("#summary", Static)
            alerts = self.query_one("#alerts", Static)
        except NoMatches:
            return
        summary.update(_render_summary(snapshot))
        self._refreshing_tables = True
        try:
            self._update_teams_table(snapshot)
            self._update_runs_table(snapshot)
            self._update_agents_table(snapshot)
            self._update_routes_table(snapshot)
            self._update_sessions_table(snapshot)
        finally:
            self._refreshing_tables = False
        alerts.update(_render_alerts(snapshot))

    def _update_teams_table(self, snapshot: OperatorSnapshot) -> None:
        table = self.query_one("#teams", DataTable)
        table.clear(columns=False)
        for team in snapshot.teams:
            table.add_row(
                team.name,
                team.lead_agent,
                str(team.active_runs),
                str(team.total_tokens),
                f"${team.estimated_total_cost_usd:.6f}",
                key=team.name,
            )

    def _update_runs_table(self, snapshot: OperatorSnapshot) -> None:
        table = self.query_one("#runs", DataTable)
        table.clear(columns=False)
        self._run_row_ids = []
        for run in snapshot.runs[:20]:
            self._run_row_ids.append(run.run_id)
            table.add_row(
                run.run_id,
                run.agent_name,
                run.status,
                str(run.total_tokens),
                f"${run.estimated_total_cost_usd:.6f}",
                str(run.context_pressure_percent),
                run.session_id,
                key=run.run_id,
            )

    def _update_agents_table(self, snapshot: OperatorSnapshot) -> None:
        table = self.query_one("#agents", DataTable)
        table.clear(columns=False)
        for agent in snapshot.agents:
            table.add_row(
                agent.name,
                agent.state,
                str(agent.active_runs),
                str(agent.total_tokens),
                f"${agent.estimated_total_cost_usd:.6f}",
                key=agent.name,
            )

    def _update_routes_table(self, snapshot: OperatorSnapshot) -> None:
        table = self.query_one("#routes", DataTable)
        table.clear(columns=False)
        self._route_row_keys = []
        self._routes_by_key = {}
        for route in snapshot.routes[:20]:
            route_key = f"{route.target_agent}|{route.thread_key}"
            self._route_row_keys.append(route_key)
            self._routes_by_key[route_key] = route
            table.add_row(
                route.target_agent,
                route.thread_key,
                route.session_id,
                key=route_key,
            )

    def _update_sessions_table(self, snapshot: OperatorSnapshot) -> None:
        table = self.query_one("#sessions", DataTable)
        table.clear(columns=False)
        self._session_row_ids = []
        for session in snapshot.sessions[:20]:
            self._session_row_ids.append(session.id)
            table.add_row(
                session.id,
                session.title,
                session.updated_at,
                key=session.id,
            )

    def _inspect_table_row(self, table_id: str, row_index: int) -> None:
        if row_index < 0:
            return
        if table_id == "runs" and row_index < len(self._run_row_ids):
            self.inspect_run(self._run_row_ids[row_index])
            return
        if table_id == "sessions" and row_index < len(self._session_row_ids):
            self.inspect_session(self._session_row_ids[row_index])
            return
        if table_id == "routes" and row_index < len(self._route_row_keys):
            self.inspect_route(self._route_row_keys[row_index])

    def _selected_identifier(self) -> str | None:
        focused = self.focused
        if not isinstance(focused, DataTable):
            return None
        row_index = focused.cursor_row
        if row_index < 0:
            return None
        table_id = str(focused.id)
        if table_id == "runs" and row_index < len(self._run_row_ids):
            return self._run_row_ids[row_index]
        if table_id == "sessions" and row_index < len(self._session_row_ids):
            return self._session_row_ids[row_index]
        if table_id == "routes" and row_index < len(self._route_row_keys):
            route = self._routes_by_key.get(self._route_row_keys[row_index])
            return None if route is None else route.session_id
        return None

    def _show_detail(self, text: str) -> None:
        self._detail_mode = True
        detail = self.query_one("#detail", Static)
        detail.display = True
        detail.update(text)


def run_ops(*, cwd: Path | None = None) -> None:
    service = OperatorService.discover_default(cwd=Path.cwd() if cwd is None else cwd, home=Path.home())
    OperatorApp(service).run()


def _render_summary(snapshot: OperatorSnapshot) -> str:
    summary = snapshot.summary
    return (
        "AgentOS Ops\n"
        f"active_runs={summary.active_runs}  "
        f"completed_runs={summary.completed_runs}  "
        f"failed_runs={summary.failed_runs}  "
        f"tokens={summary.total_tokens}  "
        f"est_cost=${summary.estimated_total_cost_usd:.6f}"
    )


def _render_alerts(snapshot: OperatorSnapshot) -> str:
    lines = ["Alerts"]
    alerts: list[str] = []
    for run in snapshot.runs:
        if run.status == "failed":
            alerts.append(f"FAIL {run.run_id} {run.agent_name}")
        elif run.context_pressure_percent >= 85:
            alerts.append(f"WARN {run.run_id} context={run.context_pressure_percent}%")
        elif run.status == "cancelling":
            alerts.append(f"INFO {run.run_id} cancelling")
    if not alerts:
        alerts.append("No alerts.")
    lines.extend(alerts[:10])
    return "\n".join(lines)


def _render_run_detail(run: RunRecord) -> str:
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
    return "\n".join(lines)


def _render_session_detail(session: SessionRecord) -> str:
    return "\n".join(
        [
            f"Inspect Session: {session.id}",
            "",
            f"title={session.title}",
            f"cwd={session.cwd}",
            f"created={session.created_at}",
            f"updated={session.updated_at}",
            "",
            "State",
            f"messages={len(session.messages)}",
            f"todos={len(session.todos)}",
            f"audit_entries={len(session.audit_log)}",
            f"token_turns={len(session.token_usage)}",
        ]
    )


def _render_route_detail(route: SessionRoute) -> str:
    return "\n".join(
        [
            "Inspect Route",
            "",
            f"agent={route.target_agent}",
            f"thread={route.thread_key}",
            f"session={route.session_id}",
            f"created={route.created_at}",
            f"updated={route.updated_at}",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "Commands",
            "",
            "/help",
            "/refresh",
            "/inspect run <id>",
            "/inspect session <id>",
            "/cancel run <id>",
            "/quit",
            "/back",
            "",
            "Keys",
            "",
            "Tab / Shift+Tab : move focus",
            "Arrow keys        : move selection in tables",
            "Enter / click     : inspect focused row",
            "Ctrl+Y            : copy selected run/session id",
            "/                 : focus command bar",
            "Esc               : close detail",
            "Ctrl+R            : refresh",
            "Ctrl+Q            : quit",
        ]
    )
