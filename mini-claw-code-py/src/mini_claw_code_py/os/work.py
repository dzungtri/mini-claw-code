from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .envelopes import utc_now_iso


TEAM_CONFIG_FILE_NAME = ".teams.json"
GOAL_STATUSES = ("pending", "in_progress", "blocked", "completed")
TASK_STATUSES = ("pending", "in_progress", "blocked", "completed")
RUN_STATUSES = ("running", "cancelling", "completed", "failed", "cancelled")


@dataclass(slots=True)
class TeamDefinition:
    name: str
    description: str
    lead_agent: str
    member_agents: tuple[str, ...]

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.description = " ".join(self.description.split()).strip() or f"Team {self.name}"
        self.lead_agent = self.lead_agent.strip()
        self.member_agents = tuple(agent.strip() for agent in self.member_agents if agent.strip())
        if not self.name:
            raise ValueError("team name cannot be empty")
        if not self.lead_agent:
            raise ValueError("lead_agent cannot be empty")
        if not self.member_agents:
            self.member_agents = (self.lead_agent,)


class TeamRegistry:
    def __init__(self, teams: Mapping[str, TeamDefinition] | None = None) -> None:
        self._teams = dict(teams or {})

    @classmethod
    def discover(cls, paths: list[Path]) -> "TeamRegistry":
        merged: dict[str, dict[str, object]] = {}
        for path in paths:
            for name, raw in _parse_team_registry_raw(path).items():
                current = merged.get(name, {})
                merged[name] = {**current, **raw}
        teams = {
            name: _team_from_raw(name, raw)
            for name, raw in merged.items()
        }
        if "default" not in teams:
            teams["default"] = default_team_definition()
        return cls(teams)

    @classmethod
    def discover_default(
        cls,
        *,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "TeamRegistry":
        return cls.discover(default_team_config_paths(cwd=cwd, home=home))

    def all(self) -> list[TeamDefinition]:
        return [self._teams[name] for name in sorted(self._teams)]

    def get(self, name: str) -> TeamDefinition | None:
        return self._teams.get(name)

    def require(self, name: str) -> TeamDefinition:
        team = self.get(name)
        if team is None:
            raise KeyError(f"unknown team: {name}")
        return team

    def render(self) -> str:
        if not self._teams:
            return "Teams: none."
        lines = ["Teams:"]
        for team in self.all():
            lines.append(f"- {team.name}: {team.description}")
            lines.append(f"  lead={team.lead_agent}")
            lines.append(f"  members={', '.join(team.member_agents)}")
        return "\n".join(lines)


@dataclass(slots=True)
class GoalRecord:
    goal_id: str
    title: str
    description: str
    primary_team: str
    status: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        self.title = " ".join(self.title.split()).strip()
        self.description = self.description.strip()
        self.primary_team = self.primary_team.strip()
        _validate_status(self.status, GOAL_STATUSES, "goal")

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "GoalRecord":
        return cls(**raw)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    goal_id: str
    team_id: str
    agent_name: str
    title: str
    status: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        self.goal_id = self.goal_id.strip()
        self.team_id = self.team_id.strip()
        self.agent_name = self.agent_name.strip()
        self.title = " ".join(self.title.split()).strip()
        _validate_status(self.status, TASK_STATUSES, "task")

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "TaskRecord":
        return cls(**raw)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    task_id: str | None
    agent_name: str
    source: str
    thread_key: str
    session_id: str
    trace_id: str
    status: str
    started_at: str
    finished_at: str | None
    turn_count: int = 0
    tool_call_count: int = 0
    subagent_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_input_cost_usd: float = 0.0
    estimated_output_cost_usd: float = 0.0
    estimated_total_cost_usd: float = 0.0
    context_pressure_percent: int = 0
    pricing_key: str = ""
    provider_name: str = ""
    model_name: str = ""

    def __post_init__(self) -> None:
        if self.task_id is not None:
            self.task_id = self.task_id.strip()
        self.agent_name = self.agent_name.strip()
        self.source = self.source.strip()
        self.thread_key = self.thread_key.strip()
        self.session_id = self.session_id.strip()
        self.trace_id = self.trace_id.strip()
        self.pricing_key = self.pricing_key.strip()
        self.provider_name = self.provider_name.strip()
        self.model_name = self.model_name.strip()
        _validate_status(self.status, RUN_STATUSES, "run")

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "RunRecord":
        payload = dict(raw)
        payload.setdefault("source", "unknown")
        payload.setdefault("thread_key", "unknown")
        payload.setdefault("turn_count", 0)
        payload.setdefault("tool_call_count", 0)
        payload.setdefault("subagent_count", 0)
        payload.setdefault("prompt_tokens", 0)
        payload.setdefault("completion_tokens", 0)
        payload.setdefault("total_tokens", 0)
        payload.setdefault("estimated_input_cost_usd", 0.0)
        payload.setdefault("estimated_output_cost_usd", 0.0)
        payload.setdefault("estimated_total_cost_usd", 0.0)
        payload.setdefault("context_pressure_percent", 0)
        payload.setdefault("pricing_key", "")
        payload.setdefault("provider_name", "")
        payload.setdefault("model_name", "")
        return cls(**payload)


class GoalStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "goals.json"

    def create(self, *, title: str, description: str, primary_team: str) -> GoalRecord:
        now = utc_now_iso()
        record = GoalRecord(
            goal_id=_create_os_id("goal"),
            title=title,
            description=description,
            primary_team=primary_team,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        records = self.list()
        records.append(record)
        self._write(records)
        return record

    def get(self, goal_id: str) -> GoalRecord | None:
        for record in self.list():
            if record.goal_id == goal_id:
                return record
        return None

    def list(self) -> list[GoalRecord]:
        return [GoalRecord.from_json_dict(raw) for raw in _read_store(self.path)]

    def update_status(self, goal_id: str, status: str) -> GoalRecord:
        _validate_status(status, GOAL_STATUSES, "goal")
        records = self.list()
        for index, record in enumerate(records):
            if record.goal_id != goal_id:
                continue
            updated = GoalRecord(
                goal_id=record.goal_id,
                title=record.title,
                description=record.description,
                primary_team=record.primary_team,
                status=status,
                created_at=record.created_at,
                updated_at=utc_now_iso(),
            )
            records[index] = updated
            self._write(records)
            return updated
        raise KeyError(f"unknown goal: {goal_id}")

    def _write(self, records: list[GoalRecord]) -> None:
        _write_store(self.path, [asdict(record) for record in records])


class TaskStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "tasks.json"

    def assign(self, *, goal_id: str, team_id: str, agent_name: str, title: str) -> TaskRecord:
        now = utc_now_iso()
        record = TaskRecord(
            task_id=_create_os_id("task"),
            goal_id=goal_id,
            team_id=team_id,
            agent_name=agent_name,
            title=title,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        records = self.list()
        records.append(record)
        self._write(records)
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        for record in self.list():
            if record.task_id == task_id:
                return record
        return None

    def list(self, *, goal_id: str | None = None, team_id: str | None = None) -> list[TaskRecord]:
        records = [TaskRecord.from_json_dict(raw) for raw in _read_store(self.path)]
        if goal_id is not None:
            records = [record for record in records if record.goal_id == goal_id]
        if team_id is not None:
            records = [record for record in records if record.team_id == team_id]
        return records

    def update_status(self, task_id: str, status: str) -> TaskRecord:
        _validate_status(status, TASK_STATUSES, "task")
        records = self.list()
        for index, record in enumerate(records):
            if record.task_id != task_id:
                continue
            updated = TaskRecord(
                task_id=record.task_id,
                goal_id=record.goal_id,
                team_id=record.team_id,
                agent_name=record.agent_name,
                title=record.title,
                status=status,
                created_at=record.created_at,
                updated_at=utc_now_iso(),
            )
            records[index] = updated
            self._write(records)
            return updated
        raise KeyError(f"unknown task: {task_id}")

    def _write(self, records: list[TaskRecord]) -> None:
        _write_store(self.path, [asdict(record) for record in records])


class RunStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "runs.json"

    def start(
        self,
        *,
        task_id: str | None,
        agent_name: str,
        source: str,
        thread_key: str,
        session_id: str,
        trace_id: str,
    ) -> RunRecord:
        record = RunRecord(
            run_id=_create_os_id("run"),
            task_id=task_id,
            agent_name=agent_name,
            source=source,
            thread_key=thread_key,
            session_id=session_id,
            trace_id=trace_id,
            status="running",
            started_at=utc_now_iso(),
            finished_at=None,
        )
        records = self.list()
        records.append(record)
        self._write(records)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        for record in self.list():
            if record.run_id == run_id:
                return record
        return None

    def list(self, *, task_id: str | None = None) -> list[RunRecord]:
        records = [RunRecord.from_json_dict(raw) for raw in _read_store(self.path)]
        if task_id is not None:
            records = [record for record in records if record.task_id == task_id]
        return records

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        turn_count: int | None = None,
        tool_call_count: int | None = None,
        subagent_count: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_input_cost_usd: float | None = None,
        estimated_output_cost_usd: float | None = None,
        estimated_total_cost_usd: float | None = None,
        context_pressure_percent: int | None = None,
        pricing_key: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> RunRecord:
        _validate_status(status, RUN_STATUSES, "run")
        records = self.list()
        for index, record in enumerate(records):
            if record.run_id != run_id:
                continue
            updated = RunRecord(
                run_id=record.run_id,
                task_id=record.task_id,
                agent_name=record.agent_name,
                source=record.source,
                thread_key=record.thread_key,
                session_id=record.session_id,
                trace_id=record.trace_id,
                status=status,
                started_at=record.started_at,
                finished_at=utc_now_iso(),
                turn_count=record.turn_count if turn_count is None else turn_count,
                tool_call_count=record.tool_call_count if tool_call_count is None else tool_call_count,
                subagent_count=record.subagent_count if subagent_count is None else subagent_count,
                prompt_tokens=record.prompt_tokens if prompt_tokens is None else prompt_tokens,
                completion_tokens=record.completion_tokens if completion_tokens is None else completion_tokens,
                total_tokens=record.total_tokens if total_tokens is None else total_tokens,
                estimated_input_cost_usd=(
                    record.estimated_input_cost_usd
                    if estimated_input_cost_usd is None
                    else estimated_input_cost_usd
                ),
                estimated_output_cost_usd=(
                    record.estimated_output_cost_usd
                    if estimated_output_cost_usd is None
                    else estimated_output_cost_usd
                ),
                estimated_total_cost_usd=(
                    record.estimated_total_cost_usd
                    if estimated_total_cost_usd is None
                    else estimated_total_cost_usd
                ),
                context_pressure_percent=(
                    record.context_pressure_percent
                    if context_pressure_percent is None
                    else context_pressure_percent
                ),
                pricing_key=record.pricing_key if pricing_key is None else pricing_key,
                provider_name=record.provider_name if provider_name is None else provider_name,
                model_name=record.model_name if model_name is None else model_name,
            )
            records[index] = updated
            self._write(records)
            return updated
        raise KeyError(f"unknown run: {run_id}")

    def mark_cancelling(self, run_id: str) -> RunRecord:
        records = self.list()
        for index, record in enumerate(records):
            if record.run_id != run_id:
                continue
            if record.status == "cancelling":
                return record
            if record.status != "running":
                raise ValueError(f"cannot mark run as cancelling from status={record.status}")
            updated = RunRecord(
                run_id=record.run_id,
                task_id=record.task_id,
                agent_name=record.agent_name,
                source=record.source,
                thread_key=record.thread_key,
                session_id=record.session_id,
                trace_id=record.trace_id,
                status="cancelling",
                started_at=record.started_at,
                finished_at=None,
                turn_count=record.turn_count,
                tool_call_count=record.tool_call_count,
                subagent_count=record.subagent_count,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.total_tokens,
                estimated_input_cost_usd=record.estimated_input_cost_usd,
                estimated_output_cost_usd=record.estimated_output_cost_usd,
                estimated_total_cost_usd=record.estimated_total_cost_usd,
                context_pressure_percent=record.context_pressure_percent,
                pricing_key=record.pricing_key,
                provider_name=record.provider_name,
                model_name=record.model_name,
            )
            records[index] = updated
            self._write(records)
            return updated
        raise KeyError(f"unknown run: {run_id}")

    def render(self, *, limit: int = 10) -> str:
        records = self.list()
        if not records:
            return "Runs: none."
        lines = ["Runs:"]
        for record in sorted(records, key=lambda item: item.started_at, reverse=True)[:limit]:
            lines.append(
                f"- {record.run_id}: agent={record.agent_name} status={record.status} session={record.session_id}"
            )
            lines.append(f"  source={record.source} thread={record.thread_key}")
            lines.append(f"  trace={record.trace_id} tokens={record.total_tokens} cost=${record.estimated_total_cost_usd:.4f}")
            if record.task_id:
                lines.append(f"  task={record.task_id}")
            lines.append(
                f"  turns={record.turn_count} tools={record.tool_call_count} subagents={record.subagent_count} ctx={record.context_pressure_percent}%"
            )
            lines.append(f"  started={record.started_at}")
            if record.finished_at:
                lines.append(f"  finished={record.finished_at}")
        return "\n".join(lines)

    def _write(self, records: list[RunRecord]) -> None:
        _write_store(self.path, [asdict(record) for record in records])


def default_team_config_paths(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    target_home = Path.home() if home is None else Path(home)
    paths: list[Path] = []
    home_path = (target_home / TEAM_CONFIG_FILE_NAME).expanduser().resolve()
    if home_path.exists():
        paths.append(home_path)
    project_path = (target_cwd / TEAM_CONFIG_FILE_NAME).expanduser().resolve()
    if project_path.exists() and project_path != home_path:
        paths.append(project_path)
    return paths


def parse_team_registry(path: str | Path) -> dict[str, TeamDefinition]:
    return {
        name: _team_from_raw(name, raw)
        for name, raw in _parse_team_registry_raw(path).items()
    }


def default_team_definition() -> TeamDefinition:
    return TeamDefinition(
        name="default",
        description="Default general-purpose team.",
        lead_agent="superagent",
        member_agents=("superagent",),
    )


def default_os_state_root(cwd: Path | None = None) -> Path:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    return (target_cwd / ".mini-claw" / "os").resolve()


def _create_os_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _validate_status(status: str, allowed: tuple[str, ...], kind: str) -> None:
    if status not in allowed:
        raise ValueError(f"unsupported {kind} status: {status}")


def _read_store(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"store must contain a JSON array: {path}")
    return [item for item in raw if isinstance(item, dict)]


def _write_store(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(rows, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _parse_team_registry_raw(path: str | Path) -> dict[str, dict[str, object]]:
    config_path = Path(path).expanduser().resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"team registry must contain a JSON object: {config_path}")
    teams = raw.get("teams", {})
    if not isinstance(teams, dict):
        raise ValueError("teams must be an object")
    parsed: dict[str, dict[str, object]] = {}
    for name, value in teams.items():
        if not isinstance(name, str):
            raise ValueError("team names must be strings")
        if not isinstance(value, dict):
            raise ValueError(f"team definition must be an object: {name}")
        normalized: dict[str, object] = {}
        if "description" in value:
            description = value["description"]
            if not isinstance(description, str):
                raise ValueError(f"description must be a string: {name}")
            normalized["description"] = description
        if "lead_agent" in value:
            lead_agent = value["lead_agent"]
            if not isinstance(lead_agent, str):
                raise ValueError(f"lead_agent must be a string: {name}")
            normalized["lead_agent"] = lead_agent
        if "member_agents" in value:
            member_agents = value["member_agents"]
            if not isinstance(member_agents, list) and not isinstance(member_agents, tuple):
                raise ValueError(f"member_agents must be a list: {name}")
            normalized["member_agents"] = tuple(str(agent) for agent in member_agents)
        parsed[name.strip()] = normalized
    return parsed


def _team_from_raw(name: str, raw: Mapping[str, object]) -> TeamDefinition:
    lead_agent = str(raw.get("lead_agent", "superagent"))
    member_agents_raw = raw.get("member_agents", (lead_agent,))
    return TeamDefinition(
        name=name,
        description=str(raw.get("description", f"Team {name}")),
        lead_agent=lead_agent,
        member_agents=tuple(member_agents_raw),  # type: ignore[arg-type]
    )
