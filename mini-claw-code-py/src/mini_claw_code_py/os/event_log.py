from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ..events import (
    AgentApprovalUpdate,
    AgentArtifactUpdate,
    AgentContextCompaction,
    AgentMemoryUpdate,
    AgentSubagentUpdate,
    AgentTodoUpdate,
    AgentTokenUsage,
    AgentToolCall,
)
from .envelopes import EventEnvelope, utc_now_iso


OPERATOR_EVENT_LOG_FILE_NAME = "operator_events.jsonl"


@dataclass(slots=True)
class OperatorEventRecord:
    event_id: str
    created_at: str
    kind: str
    trace_id: str
    run_id: str
    session_id: str
    target_agent: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        self.event_id = self.event_id.strip()
        self.created_at = self.created_at.strip()
        self.kind = self.kind.strip()
        self.trace_id = self.trace_id.strip()
        self.run_id = self.run_id.strip()
        self.session_id = self.session_id.strip()
        self.target_agent = self.target_agent.strip()
        if not self.event_id:
            raise ValueError("event_id cannot be empty")
        if not self.kind:
            raise ValueError("kind cannot be empty")

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        trace_id: str,
        run_id: str = "",
        session_id: str = "",
        target_agent: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> "OperatorEventRecord":
        return cls(
            event_id=f"evt_{uuid4().hex[:12]}",
            created_at=utc_now_iso(),
            kind=kind,
            trace_id=trace_id,
            run_id=run_id,
            session_id=session_id,
            target_agent=target_agent,
            payload=dict(payload or {}),
        )

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "OperatorEventRecord":
        return cls(**raw)


class OperatorEventStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / OPERATOR_EVENT_LOG_FILE_NAME

    def append(self, record: OperatorEventRecord) -> OperatorEventRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")
        return record

    def append_envelope(
        self,
        envelope: EventEnvelope,
        *,
        run_id: str = "",
        session_id: str = "",
        target_agent: str = "",
    ) -> OperatorEventRecord:
        payload = dict(envelope.payload)
        payload.setdefault("run_id", run_id)
        payload.setdefault("session_id", session_id)
        payload.setdefault("target_agent", target_agent)
        return self.append(
            OperatorEventRecord.create(
                kind=envelope.kind,
                trace_id=envelope.trace_id,
                run_id=str(payload.get("run_id", "")).strip(),
                session_id=str(payload.get("session_id", "")).strip(),
                target_agent=str(payload.get("target_agent", "")).strip(),
                payload=payload,
            )
        )

    def append_agent_event(
        self,
        event: object,
        *,
        trace_id: str,
        run_id: str,
        session_id: str,
        target_agent: str,
    ) -> OperatorEventRecord | None:
        mapped = _operator_event_from_agent_event(
            event,
            trace_id=trace_id,
            run_id=run_id,
            session_id=session_id,
            target_agent=target_agent,
        )
        if mapped is None:
            return None
        return self.append(mapped)

    def list(
        self,
        *,
        limit: int = 100,
        run_id: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[OperatorEventRecord]:
        records: list[OperatorEventRecord] = []
        for raw in _read_jsonl(self.path):
            record = OperatorEventRecord.from_json_dict(raw)
            if run_id is not None and record.run_id != run_id:
                continue
            if trace_id is not None and record.trace_id != trace_id:
                continue
            if session_id is not None and record.session_id != session_id:
                continue
            records.append(record)
        return records[-limit:]

    def render_for_run(self, run_id: str, *, limit: int = 20) -> str:
        records = self.list(run_id=run_id, limit=limit)
        if not records:
            return "Run events: none."
        lines = ["Run events:"]
        for record in records:
            lines.append(f"- {record.created_at} {record.kind}")
            summary = _payload_summary(record.payload)
            if summary:
                lines.append(f"  {summary}")
        return "\n".join(lines)


def _operator_event_from_agent_event(
    event: object,
    *,
    trace_id: str,
    run_id: str,
    session_id: str,
    target_agent: str,
) -> OperatorEventRecord | None:
    kind: str | None = None
    payload: dict[str, Any] = {}
    if isinstance(event, AgentToolCall):
        kind = "agent.tool_call"
        payload = {"name": event.name, "summary": event.summary}
    elif isinstance(event, AgentSubagentUpdate):
        kind = "agent.subagent"
        payload = {
            "status": event.status,
            "index": event.index,
            "total": event.total,
            "brief": event.brief,
            "message": event.message,
        }
    elif isinstance(event, AgentContextCompaction):
        kind = "agent.context_compaction"
        payload = {
            "archived_messages": event.archived_messages,
            "kept_messages": event.kept_messages,
            "triggered_by": list(event.triggered_by),
            "message": event.message,
        }
    elif isinstance(event, AgentApprovalUpdate):
        kind = "agent.approval"
        payload = {
            "status": event.status,
            "tool_name": event.tool_name,
            "message": event.message,
        }
    elif isinstance(event, AgentTokenUsage):
        kind = "agent.usage"
        payload = {"message": event.message}
    elif isinstance(event, AgentTodoUpdate):
        kind = "agent.todos"
        payload = {
            "total": event.total,
            "completed": event.completed,
            "message": event.message,
        }
    elif isinstance(event, AgentMemoryUpdate):
        kind = "agent.memory"
        payload = {
            "status": event.status,
            "scope": event.scope,
            "message": event.message,
        }
    elif isinstance(event, AgentArtifactUpdate):
        kind = "agent.artifacts"
        payload = {
            "created": event.created,
            "updated": event.updated,
            "removed": event.removed,
            "message": event.message,
        }
    if kind is None:
        return None
    return OperatorEventRecord.create(
        kind=kind,
        trace_id=trace_id,
        run_id=run_id,
        session_id=session_id,
        target_agent=target_agent,
        payload=payload,
    )


def _payload_summary(payload: Mapping[str, Any]) -> str:
    summary_keys = ("message", "summary", "name", "status")
    parts: list[str] = []
    for key in summary_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}={value.strip()}")
    return " ".join(parts)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw = json.loads(stripped)
        if isinstance(raw, dict):
            rows.append(raw)
    return rows
