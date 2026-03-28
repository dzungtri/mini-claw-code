from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .context import ARCHIVED_CONTEXT_OPEN
from .control_plane import AuditEntry
from .telemetry import TokenUsageSnapshot
from .todos import TodoItem
from .types import AssistantTurn, Message, StopReason, ToolCall

if TYPE_CHECKING:
    from .harness import HarnessAgent


SESSION_VERSION = 1
DEFAULT_SESSION_TITLE = "Untitled session"
BLOB_REFERENCE_OPEN = "[Large content stored outside active session context]"


@dataclass(slots=True)
class SessionRecord:
    version: int
    id: str
    title: str
    created_at: str
    updated_at: str
    cwd: Path
    messages: list[dict[str, Any]]
    todos: list[dict[str, str]]
    audit_log: list[dict[str, str]]
    token_usage: list[dict[str, int]]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cwd": str(self.cwd),
            "messages": self.messages,
            "todos": self.todos,
            "audit_log": self.audit_log,
            "token_usage": self.token_usage,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> "SessionRecord":
        return cls(
            version=int(raw.get("version", SESSION_VERSION)),
            id=str(raw["id"]),
            title=str(raw.get("title") or DEFAULT_SESSION_TITLE),
            created_at=str(raw["created_at"]),
            updated_at=str(raw.get("updated_at") or raw["created_at"]),
            cwd=Path(str(raw["cwd"])).expanduser().resolve(),
            messages=_coerce_list_of_dicts(raw.get("messages")),
            todos=_coerce_list_of_dicts(raw.get("todos")),
            audit_log=_coerce_list_of_dicts(raw.get("audit_log")),
            token_usage=_coerce_list_of_dicts(raw.get("token_usage")),
        )


class SessionStore:
    def __init__(
        self,
        root: str | Path,
        *,
        blob_threshold_chars: int = 4000,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.blob_threshold_chars = blob_threshold_chars

    def create(self, *, cwd: str | Path, title: str | None = None) -> SessionRecord:
        now = utc_now_iso()
        return SessionRecord(
            version=SESSION_VERSION,
            id=create_session_id(),
            title=_normalize_session_title(title) if title is not None else DEFAULT_SESSION_TITLE,
            created_at=now,
            updated_at=now,
            cwd=Path(cwd).expanduser().resolve(),
            messages=[],
            todos=[],
            audit_log=[],
            token_usage=[],
        )

    def save_runtime(
        self,
        record: SessionRecord,
        *,
        messages: list[Message],
        todos: list[TodoItem],
        audit_entries: list[AuditEntry],
        token_usage: list[TokenUsageSnapshot],
    ) -> SessionRecord:
        session_dir = self.session_dir(record.id)
        blobs_dir = session_dir / "blobs"
        archive_dir = session_dir / "archive"
        session_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        if blobs_dir.exists():
            shutil.rmtree(blobs_dir)
        blobs_dir.mkdir(parents=True, exist_ok=True)

        working_messages = strip_injected_system_prompt(messages)
        record.messages = serialize_messages(
            working_messages,
            session_dir=session_dir,
            blob_threshold_chars=self.blob_threshold_chars,
        )
        record.todos = [asdict(item) for item in todos]
        record.audit_log = [asdict(entry) for entry in audit_entries]
        record.token_usage = [asdict(turn) for turn in token_usage]
        record.cwd = Path(record.cwd).expanduser().resolve()
        record.updated_at = utc_now_iso()
        if record.title == DEFAULT_SESSION_TITLE:
            record.title = derive_session_title(working_messages)

        self._write_record(record)
        return record

    def load(self, session_id: str) -> SessionRecord:
        path = self.session_dir(session_id) / "session.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SessionRecord.from_json_dict(raw)

    def persist(self, record: SessionRecord) -> SessionRecord:
        self._ensure_layout(record.id)
        self._write_record(record)
        return record

    def list_recent(self, *, limit: int | None = None) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        if not self.root.exists():
            return records
        for path in self.root.glob("*/session.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            records.append(SessionRecord.from_json_dict(raw))
        records.sort(key=lambda record: record.updated_at, reverse=True)
        if limit is not None:
            return records[:limit]
        return records

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def restore_into_agent(
        self,
        agent: "HarnessAgent",
        record: SessionRecord,
    ) -> list[Message]:
        messages = deserialize_messages(
            record.messages,
            session_dir=self.session_dir(record.id),
            inflate_blobs=False,
        )
        agent.restore_runtime_state(
            todos=list(record.todos),
            audit_entries=list(record.audit_log),
            token_usage=list(record.token_usage),
        )
        return messages

    def blob_path(self, session_id: str, content_ref: str) -> Path:
        return (self.session_dir(session_id) / content_ref).resolve()

    def read_blob(self, session_id: str, content_ref: str) -> str:
        return self.blob_path(session_id, content_ref).read_text(encoding="utf-8")

    def rename(self, record: SessionRecord, title: str) -> SessionRecord:
        record.title = _normalize_session_title(title)
        record.updated_at = utc_now_iso()
        self._ensure_layout(record.id)
        self._write_record(record)
        return record

    def fork(self, record: SessionRecord, *, title: str | None = None) -> SessionRecord:
        self._ensure_layout(record.id)
        self._write_record(record)

        forked = SessionRecord.from_json_dict(record.to_json_dict())
        now = utc_now_iso()
        forked.id = create_session_id()
        forked.title = (
            _normalize_session_title(title)
            if title is not None
            else _fork_title(record.title)
        )
        forked.created_at = now
        forked.updated_at = now

        source_dir = self.session_dir(record.id)
        target_dir = self.session_dir(forked.id)
        shutil.copytree(source_dir, target_dir)
        self._write_record(forked)
        return forked

    def _write_record(self, record: SessionRecord) -> None:
        path = self.session_dir(record.id) / "session.json"
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(record.to_json_dict(), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _ensure_layout(self, session_id: str) -> None:
        session_dir = self.session_dir(session_id)
        (session_dir / "blobs").mkdir(parents=True, exist_ok=True)
        (session_dir / "archive").mkdir(parents=True, exist_ok=True)


def create_session_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"sess_{stamp}_{uuid.uuid4().hex[:6]}"


def derive_session_title(messages: list[Message]) -> str:
    for message in messages:
        if message.kind != "user" or not message.content:
            continue
        text = " ".join(message.content.strip().split())
        if not text:
            continue
        text = text.strip("\"'` ")
        if len(text) > 72:
            text = text[:69].rstrip() + "..."
        return text or DEFAULT_SESSION_TITLE
    return DEFAULT_SESSION_TITLE


def _normalize_session_title(title: str) -> str:
    normalized = " ".join(title.strip().split())
    if not normalized:
        raise ValueError("session title cannot be empty")
    return normalized


def _fork_title(title: str) -> str:
    normalized = title.strip() or DEFAULT_SESSION_TITLE
    return f"{normalized} (fork)"


def strip_injected_system_prompt(messages: list[Message]) -> list[Message]:
    if not messages:
        return []
    first = messages[0]
    if _is_injected_system_prompt(first):
        return list(messages[1:])
    return list(messages)


def serialize_messages(
    messages: list[Message],
    *,
    session_dir: Path,
    blob_threshold_chars: int = 4000,
) -> list[dict[str, Any]]:
    blob_counter = {"next": 1}
    serialized: list[dict[str, Any]] = []
    for message in messages:
        record: dict[str, Any] = {"kind": message.kind}
        if message.kind in {"user", "tool_result", "system"}:
            record.update(
                _serialize_text_payload(
                    message.content or "",
                    session_dir=session_dir,
                    blob_threshold_chars=blob_threshold_chars,
                    blob_counter=blob_counter,
                )
            )
            if message.tool_call_id is not None:
                record["tool_call_id"] = message.tool_call_id
            serialized.append(record)
            continue

        if message.kind == "assistant" and message.turn is not None:
            turn = message.turn
            record["stop_reason"] = turn.stop_reason.value
            record["tool_calls"] = [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in turn.tool_calls
            ]
            record.update(
                _serialize_text_payload(
                    turn.text or "",
                    session_dir=session_dir,
                    blob_threshold_chars=blob_threshold_chars,
                    blob_counter=blob_counter,
                )
            )
            serialized.append(record)
        else:
            raise ValueError(f"unsupported message kind: {message.kind}")
    return serialized


def deserialize_messages(
    records: list[dict[str, Any]],
    *,
    session_dir: Path,
    inflate_blobs: bool = False,
) -> list[Message]:
    messages: list[Message] = []
    for record in records:
        kind = str(record.get("kind", ""))
        if kind == "user":
            messages.append(
                Message.user(
                    _deserialize_text_payload(
                        record,
                        session_dir=session_dir,
                        inflate_blobs=inflate_blobs,
                    )
                )
            )
            continue
        if kind == "tool_result":
            messages.append(
                Message.tool_result(
                    str(record.get("tool_call_id", "")),
                    _deserialize_text_payload(
                        record,
                        session_dir=session_dir,
                        inflate_blobs=inflate_blobs,
                    ),
                )
            )
            continue
        if kind == "system":
            messages.append(
                Message.system(
                    _deserialize_text_payload(
                        record,
                        session_dir=session_dir,
                        inflate_blobs=inflate_blobs,
                    )
                )
            )
            continue
        if kind == "assistant":
            tool_calls = [
                ToolCall(
                    id=str(raw.get("id", "")),
                    name=str(raw.get("name", "")),
                    arguments=raw.get("arguments"),
                )
                for raw in _coerce_list_of_dicts(record.get("tool_calls"))
            ]
            stop_reason = StopReason(str(record.get("stop_reason", StopReason.STOP.value)))
            text = _deserialize_text_payload(
                record,
                session_dir=session_dir,
                inflate_blobs=inflate_blobs,
            )
            messages.append(
                Message.assistant(
                    AssistantTurn(
                        text=text or None,
                        tool_calls=tool_calls,
                        stop_reason=stop_reason,
                    )
                )
            )
            continue
        raise ValueError(f"unsupported message kind: {kind}")
    return messages


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _serialize_text_payload(
    text: str,
    *,
    session_dir: Path,
    blob_threshold_chars: int,
    blob_counter: dict[str, int],
) -> dict[str, str]:
    if len(text) <= blob_threshold_chars:
        return {"content": text}

    blob_name = f"msg_{blob_counter['next']:04d}.txt"
    blob_counter["next"] += 1
    blob_path = session_dir / "blobs" / blob_name
    blob_path.write_text(text, encoding="utf-8")
    return {
        "content_ref": f"blobs/{blob_name}",
        "preview": _preview_text(text),
    }


def _deserialize_text_payload(
    record: dict[str, Any],
    *,
    session_dir: Path,
    inflate_blobs: bool,
) -> str:
    inline = record.get("content")
    if isinstance(inline, str):
        return inline
    ref = record.get("content_ref")
    if isinstance(ref, str) and ref:
        if inflate_blobs:
            return (session_dir / ref).read_text(encoding="utf-8")
        preview = record.get("preview")
        return _render_blob_reference(
            blob_path=(session_dir / ref).resolve(),
            preview=preview if isinstance(preview, str) else "",
        )
    return ""


def _preview_text(text: str, limit: int = 120) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _render_blob_reference(*, blob_path: Path, preview: str) -> str:
    lines = [
        BLOB_REFERENCE_OPEN,
        f"Blob path: {blob_path}",
    ]
    if preview:
        lines.append(f"Preview: {preview}")
    lines.append("Use the read tool only if the full body is needed.")
    return "\n".join(lines)


def _is_injected_system_prompt(message: Message) -> bool:
    return (
        message.kind == "system"
        and isinstance(message.content, str)
        and not message.content.strip().startswith(ARCHIVED_CONTEXT_OPEN)
    )


def _coerce_list_of_dicts(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]
