from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..session import SessionRecord, SessionStore
from .agent_registry import HostedAgentRegistry
from .control import RunControlStore
from .event_log import OperatorEventRecord, OperatorEventStore
from .session_router import RouteStore, SessionRoute
from .work import GoalStore, RunRecord, RunStore, TaskStore, TeamRegistry


@dataclass(slots=True)
class OperatorSummary:
    active_runs: int
    completed_runs: int
    failed_runs: int
    total_tokens: int
    estimated_total_cost_usd: float


@dataclass(slots=True)
class OperatorSnapshot:
    summary: OperatorSummary
    agents: list["AgentStatusView"]
    teams: list["TeamStatusView"]
    routes: list[SessionRoute]
    runs: list[RunRecord]
    sessions: list[SessionRecord]


@dataclass(slots=True)
class AgentStatusView:
    name: str
    description: str
    state: str
    active_runs: int
    total_tokens: int
    estimated_total_cost_usd: float


@dataclass(slots=True)
class TeamStatusView:
    name: str
    description: str
    lead_agent: str
    active_runs: int
    total_tokens: int
    estimated_total_cost_usd: float


class OperatorService:
    def __init__(
        self,
        *,
        registry: HostedAgentRegistry,
        teams: TeamRegistry,
        routes: RouteStore,
        sessions: SessionStore,
        goals: GoalStore | None = None,
        tasks: TaskStore | None = None,
        runs: RunStore,
        controls: RunControlStore | None = None,
        events: OperatorEventStore | None = None,
    ) -> None:
        self.registry = registry
        self.teams = teams
        self.routes = routes
        self.sessions = sessions
        self.goals = goals
        self.tasks = tasks
        self.runs = runs
        self.controls = controls or RunControlStore(runs.root)
        self.events = events or OperatorEventStore(runs.root)

    @classmethod
    def discover_default(cls, *, cwd: Path | None = None, home: Path | None = None) -> "OperatorService":
        target_cwd = Path.cwd() if cwd is None else Path(cwd)
        target_home = Path.home() if home is None else Path(home)
        sessions = SessionStore(target_cwd / ".mini-claw" / "sessions")
        os_root = target_cwd / ".mini-claw" / "os"
        return cls(
            registry=HostedAgentRegistry.discover_default(cwd=target_cwd, home=target_home),
            teams=TeamRegistry.discover_default(cwd=target_cwd, home=target_home),
            routes=RouteStore(os_root),
            sessions=sessions,
            goals=GoalStore(os_root),
            tasks=TaskStore(os_root),
            runs=RunStore(os_root),
            controls=RunControlStore(os_root),
            events=OperatorEventStore(os_root),
        )

    def snapshot(self, *, run_limit: int = 20, session_limit: int = 20) -> OperatorSnapshot:
        runs = sorted(self.runs.list(), key=lambda item: item.started_at, reverse=True)
        sessions = self.sessions.list_recent(limit=session_limit)
        return OperatorSnapshot(
            summary=OperatorSummary(
                active_runs=sum(1 for run in runs if run.status in {"running", "cancelling"}),
                completed_runs=sum(1 for run in runs if run.status == "completed"),
                failed_runs=sum(1 for run in runs if run.status == "failed"),
                total_tokens=sum(run.total_tokens for run in runs),
                estimated_total_cost_usd=sum(run.estimated_total_cost_usd for run in runs),
            ),
            agents=self.list_agents(runs=runs),
            teams=self.list_teams(runs=runs),
            routes=self.routes.list(),
            runs=runs[:run_limit],
            sessions=sessions,
        )

    def list_runs(self, *, limit: int = 20) -> list[RunRecord]:
        return self.snapshot(run_limit=limit).runs

    def inspect_run(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    def inspect_run_events(self, run_id: str, *, limit: int = 20) -> list[OperatorEventRecord]:
        return self.events.list(run_id=run_id, limit=limit)

    def inspect_session(self, session_id: str) -> SessionRecord | None:
        try:
            return self.sessions.load(session_id)
        except FileNotFoundError:
            return None

    def inspect_route(self, *, target_agent: str, thread_key: str) -> SessionRoute | None:
        return self.routes.resolve(target_agent=target_agent, thread_key=thread_key)

    def cancel_run(
        self,
        run_id: str,
        *,
        actor: str = "operator",
        reason: str = "",
    ) -> str:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        if run.status == "running":
            self.controls.request_cancel(run_id, actor=actor, reason=reason)
            self.runs.mark_cancelling(run_id)
            return f"Cancellation requested for {run_id}."
        if run.status == "cancelling":
            return f"Run {run_id} is already cancelling."
        return f"Run {run_id} is already {run.status}."

    def list_routes(self) -> list[SessionRoute]:
        return self.routes.list()

    def list_sessions(self, *, limit: int = 20) -> list[SessionRecord]:
        return self.sessions.list_recent(limit=limit)

    def list_agents(self, *, runs: list[RunRecord] | None = None) -> list[AgentStatusView]:
        active_runs = self.runs.list() if runs is None else runs
        views: list[AgentStatusView] = []
        for definition in self.registry.all():
            agent_runs = [run for run in active_runs if run.agent_name == definition.name]
            active_count = sum(1 for run in agent_runs if run.status in {"running", "cancelling"})
            state = "busy" if active_count else "idle"
            views.append(
                AgentStatusView(
                    name=definition.name,
                    description=definition.description,
                    state=state,
                    active_runs=active_count,
                    total_tokens=sum(run.total_tokens for run in agent_runs),
                    estimated_total_cost_usd=sum(run.estimated_total_cost_usd for run in agent_runs),
                )
            )
        return views

    def list_teams(self, *, runs: list[RunRecord] | None = None) -> list[TeamStatusView]:
        active_runs = self.runs.list() if runs is None else runs
        views: list[TeamStatusView] = []
        for team in self.teams.all():
            team_runs = [
                run
                for run in active_runs
                if run.agent_name == team.lead_agent or run.agent_name in team.member_agents
            ]
            views.append(
                TeamStatusView(
                    name=team.name,
                    description=team.description,
                    lead_agent=team.lead_agent,
                    active_runs=sum(1 for run in team_runs if run.status in {"running", "cancelling"}),
                    total_tokens=sum(run.total_tokens for run in team_runs),
                    estimated_total_cost_usd=sum(run.estimated_total_cost_usd for run in team_runs),
                )
            )
        return views
