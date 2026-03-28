from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Mapping

from .bus import MessageBus
from .envelopes import EventEnvelope, MessageEnvelope, create_envelope_id, utc_now_iso
from .work import TeamRegistry, _read_store, _write_store


HEARTBEAT_FILE_NAME = "HEARTBEAT.md"
CRON_FILE_NAME = "cron_jobs.json"
CronKind = Literal["every", "at"]


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


def _resolve_background_target(
    *,
    target_agent: str | None,
    target_team: str | None,
    teams: TeamRegistry | None,
) -> str:
    if target_agent and target_agent.strip():
        return target_agent.strip()
    if target_team and target_team.strip():
        if teams is None:
            raise ValueError("target_team requires a team registry")
        return teams.require(target_team.strip()).lead_agent
    raise ValueError("background work requires target_agent or target_team")


def heartbeat_has_actionable_work(path: str | Path) -> bool:
    heartbeat_path = Path(path).expanduser().resolve()
    if not heartbeat_path.exists():
        return False
    for raw_line in heartbeat_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.lstrip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if (line.startswith("- [x]") or line.startswith("- [X]") or line.startswith("* [x]") or line.startswith("* [X]")):
            continue
        return True
    return False


@dataclass(slots=True)
class CronJob:
    job_id: str
    name: str
    kind: CronKind
    content: str
    target_agent: str | None
    target_team: str | None
    enabled: bool
    created_at: str
    updated_at: str
    next_run_at: str
    every_seconds: int | None = None
    run_at: str | None = None
    last_run_at: str | None = None

    def __post_init__(self) -> None:
        self.job_id = self.job_id.strip()
        self.name = " ".join(self.name.split()).strip()
        self.content = self.content.strip()
        self.target_agent = None if self.target_agent is None else self.target_agent.strip() or None
        self.target_team = None if self.target_team is None else self.target_team.strip() or None
        self.created_at = self.created_at.strip()
        self.updated_at = self.updated_at.strip()
        self.next_run_at = self.next_run_at.strip()
        self.run_at = None if self.run_at is None else self.run_at.strip() or None
        self.last_run_at = None if self.last_run_at is None else self.last_run_at.strip() or None
        if not self.job_id:
            raise ValueError("job_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if self.kind not in {"every", "at"}:
            raise ValueError(f"unsupported cron kind: {self.kind}")
        if not self.content:
            raise ValueError("content cannot be empty")
        if self.target_agent is None and self.target_team is None:
            raise ValueError("cron job requires target_agent or target_team")
        if self.kind == "every":
            if self.every_seconds is None or self.every_seconds <= 0:
                raise ValueError("every cron jobs require every_seconds > 0")
        if self.kind == "at":
            if not self.run_at:
                raise ValueError("at cron jobs require run_at")

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "CronJob":
        return cls(**raw)


class CronStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / CRON_FILE_NAME

    def list(self) -> list[CronJob]:
        return [CronJob.from_json_dict(raw) for raw in _read_store(self.path)]

    def get(self, job_id: str) -> CronJob | None:
        for job in self.list():
            if job.job_id == job_id:
                return job
        return None

    def create_every(
        self,
        *,
        name: str,
        content: str,
        every_seconds: int,
        target_agent: str | None = None,
        target_team: str | None = None,
        now: datetime | None = None,
    ) -> CronJob:
        current = _now_utc() if now is None else now.astimezone(UTC)
        job = CronJob(
            job_id=create_envelope_id("cron"),
            name=name,
            kind="every",
            content=content,
            target_agent=target_agent,
            target_team=target_team,
            enabled=True,
            created_at=current.isoformat().replace("+00:00", "Z"),
            updated_at=current.isoformat().replace("+00:00", "Z"),
            next_run_at=(current + timedelta(seconds=every_seconds)).isoformat().replace("+00:00", "Z"),
            every_seconds=every_seconds,
        )
        jobs = self.list()
        jobs.append(job)
        self._write(jobs)
        return job

    def create_at(
        self,
        *,
        name: str,
        content: str,
        run_at: str,
        target_agent: str | None = None,
        target_team: str | None = None,
        now: datetime | None = None,
    ) -> CronJob:
        current = _now_utc() if now is None else now.astimezone(UTC)
        scheduled = _parse_iso_datetime(run_at)
        job = CronJob(
            job_id=create_envelope_id("cron"),
            name=name,
            kind="at",
            content=content,
            target_agent=target_agent,
            target_team=target_team,
            enabled=True,
            created_at=current.isoformat().replace("+00:00", "Z"),
            updated_at=current.isoformat().replace("+00:00", "Z"),
            next_run_at=scheduled.isoformat().replace("+00:00", "Z"),
            run_at=scheduled.isoformat().replace("+00:00", "Z"),
        )
        jobs = self.list()
        jobs.append(job)
        self._write(jobs)
        return job

    def due(self, *, now: datetime | None = None) -> list[CronJob]:
        current = _now_utc() if now is None else now.astimezone(UTC)
        due_jobs = []
        for job in self.list():
            if not job.enabled:
                continue
            if _parse_iso_datetime(job.next_run_at) <= current:
                due_jobs.append(job)
        return due_jobs

    def mark_ran(self, job_id: str, *, now: datetime | None = None) -> CronJob:
        current = _now_utc() if now is None else now.astimezone(UTC)
        jobs = self.list()
        for index, job in enumerate(jobs):
            if job.job_id != job_id:
                continue
            if job.kind == "every":
                assert job.every_seconds is not None
                next_run = current + timedelta(seconds=job.every_seconds)
                updated = CronJob(
                    job_id=job.job_id,
                    name=job.name,
                    kind=job.kind,
                    content=job.content,
                    target_agent=job.target_agent,
                    target_team=job.target_team,
                    enabled=job.enabled,
                    created_at=job.created_at,
                    updated_at=current.isoformat().replace("+00:00", "Z"),
                    next_run_at=next_run.isoformat().replace("+00:00", "Z"),
                    every_seconds=job.every_seconds,
                    run_at=job.run_at,
                    last_run_at=current.isoformat().replace("+00:00", "Z"),
                )
            else:
                updated = CronJob(
                    job_id=job.job_id,
                    name=job.name,
                    kind=job.kind,
                    content=job.content,
                    target_agent=job.target_agent,
                    target_team=job.target_team,
                    enabled=False,
                    created_at=job.created_at,
                    updated_at=current.isoformat().replace("+00:00", "Z"),
                    next_run_at=job.next_run_at,
                    run_at=job.run_at,
                    last_run_at=current.isoformat().replace("+00:00", "Z"),
                )
            jobs[index] = updated
            self._write(jobs)
            return updated
        raise KeyError(f"unknown cron job: {job_id}")

    def render(self) -> str:
        jobs = self.list()
        if not jobs:
            return "Cron jobs: none."
        lines = ["Cron jobs:"]
        for job in sorted(jobs, key=lambda item: item.next_run_at):
            target = job.target_agent if job.target_agent else f"team:{job.target_team}"
            lines.append(
                f"- {job.job_id}: {job.name} kind={job.kind} enabled={job.enabled} target={target}"
            )
            lines.append(f"  next_run_at={job.next_run_at}")
        return "\n".join(lines)

    def _write(self, jobs: list[CronJob]) -> None:
        _write_store(self.path, [asdict(job) for job in jobs])


class HeartbeatService:
    def __init__(
        self,
        *,
        cwd: str | Path,
        bus: MessageBus,
        teams: TeamRegistry | None = None,
        heartbeat_file: str = HEARTBEAT_FILE_NAME,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.bus = bus
        self.teams = teams
        self.heartbeat_path = self.cwd / heartbeat_file

    def has_actionable_work(self) -> bool:
        return heartbeat_has_actionable_work(self.heartbeat_path)

    async def trigger(
        self,
        *,
        target_agent: str | None = None,
        target_team: str | None = None,
        thread_key: str = "system:heartbeat",
    ) -> MessageEnvelope | None:
        if not self.has_actionable_work():
            return None
        resolved_target = _resolve_background_target(
            target_agent=target_agent,
            target_team=target_team,
            teams=self.teams,
        )
        envelope = MessageEnvelope(
            source="heartbeat",
            target_agent=resolved_target,
            thread_key=thread_key,
            kind="background_message",
            content=(
                f"Read {self.heartbeat_path.name} and follow any actionable instructions. "
                "If nothing needs attention, reply with HEARTBEAT_OK."
            ),
            metadata={"service": "heartbeat"},
        )
        await self.bus.publish_inbound(envelope)
        await self.bus.publish_event(
            EventEnvelope(
                kind="operator_event",
                trace_id=envelope.trace_id,
                payload={
                    "service": "heartbeat",
                    "action": "published",
                    "message_id": envelope.message_id,
                    "target_agent": envelope.target_agent,
                },
            )
        )
        return envelope


class CronService:
    def __init__(
        self,
        *,
        store: CronStore,
        bus: MessageBus,
        teams: TeamRegistry | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.teams = teams

    async def fire_due(self, *, now: datetime | None = None, limit: int | None = None) -> list[MessageEnvelope]:
        current = _now_utc() if now is None else now.astimezone(UTC)
        published: list[MessageEnvelope] = []
        for job in self.store.due(now=current)[:limit]:
            resolved_target = _resolve_background_target(
                target_agent=job.target_agent,
                target_team=job.target_team,
                teams=self.teams,
            )
            envelope = MessageEnvelope(
                source=f"cron:{job.job_id}",
                target_agent=resolved_target,
                thread_key=f"cron:{job.job_id}",
                kind="background_message",
                content=job.content,
                metadata={"service": "cron", "cron_job_id": job.job_id},
            )
            await self.bus.publish_inbound(envelope)
            await self.bus.publish_event(
                EventEnvelope(
                    kind="operator_event",
                    trace_id=envelope.trace_id,
                    payload={
                        "service": "cron",
                        "action": "published",
                        "job_id": job.job_id,
                        "message_id": envelope.message_id,
                        "target_agent": envelope.target_agent,
                    },
                )
            )
            self.store.mark_ran(job.job_id, now=current)
            published.append(envelope)
        return published
