from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4


MessageKind = Literal["user_message", "system_message", "background_message"]
EventKind = Literal["run_started", "run_finished", "outbound_message", "operator_event"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_envelope_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def create_trace_id() -> str:
    return f"trace_{uuid4().hex}"


@dataclass(slots=True)
class MessageEnvelope:
    source: str
    target_agent: str
    thread_key: str
    kind: MessageKind
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=create_envelope_id)
    trace_id: str = field(default_factory=create_trace_id)
    parent_run_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.source = self.source.strip()
        self.target_agent = self.target_agent.strip()
        self.thread_key = self.thread_key.strip()
        if not self.source:
            raise ValueError("source cannot be empty")
        if not self.target_agent:
            raise ValueError("target_agent cannot be empty")
        if not self.thread_key:
            raise ValueError("thread_key cannot be empty")
        if self.kind not in {"user_message", "system_message", "background_message"}:
            raise ValueError(f"unsupported message kind: {self.kind}")
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")


@dataclass(slots=True)
class EventEnvelope:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=create_trace_id)
    event_id: str = field(default_factory=lambda: create_envelope_id("evt"))
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.kind not in {"run_started", "run_finished", "outbound_message", "operator_event"}:
            raise ValueError(f"unsupported event kind: {self.kind}")
