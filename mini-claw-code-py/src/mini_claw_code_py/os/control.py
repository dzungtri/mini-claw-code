from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .envelopes import utc_now_iso
from .work import _read_store, _write_store


CONTROL_ACTIONS = ("cancel_run",)
CONTROL_RESULTS = ("pending", "cancelled", "rejected", "completed")


@dataclass(slots=True)
class RunControlRecord:
    run_id: str
    action: str
    actor: str
    reason: str
    requested_at: str
    resolved_at: str | None
    result: str

    def __post_init__(self) -> None:
        self.run_id = self.run_id.strip()
        self.action = self.action.strip()
        self.actor = self.actor.strip()
        self.reason = self.reason.strip()
        self.result = self.result.strip()
        if not self.run_id:
            raise ValueError("run_id cannot be empty")
        if self.action not in CONTROL_ACTIONS:
            raise ValueError(f"unsupported control action: {self.action}")
        if self.result not in CONTROL_RESULTS:
            raise ValueError(f"unsupported control result: {self.result}")

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "RunControlRecord":
        payload = dict(raw)
        payload.setdefault("reason", "")
        payload.setdefault("resolved_at", None)
        payload.setdefault("result", "pending")
        return cls(**payload)


class RunControlStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "run_controls.json"

    def list(self) -> list[RunControlRecord]:
        return [RunControlRecord.from_json_dict(raw) for raw in _read_store(self.path)]

    def latest(self, run_id: str) -> RunControlRecord | None:
        matches = [record for record in self.list() if record.run_id == run_id]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.requested_at)[-1]

    def request_cancel(
        self,
        run_id: str,
        *,
        actor: str = "operator",
        reason: str = "",
    ) -> RunControlRecord:
        current = self.latest(run_id)
        if current is not None and current.result == "pending" and current.action == "cancel_run":
            return current
        record = RunControlRecord(
            run_id=run_id,
            action="cancel_run",
            actor=actor,
            reason=reason,
            requested_at=utc_now_iso(),
            resolved_at=None,
            result="pending",
        )
        records = self.list()
        records.append(record)
        self._write(records)
        return record

    def is_cancel_requested(self, run_id: str) -> bool:
        current = self.latest(run_id)
        return current is not None and current.action == "cancel_run" and current.result == "pending"

    def resolve(self, run_id: str, *, result: str) -> RunControlRecord:
        if result not in CONTROL_RESULTS or result == "pending":
            raise ValueError(f"unsupported control result: {result}")
        records = self.list()
        for index in range(len(records) - 1, -1, -1):
            record = records[index]
            if record.run_id != run_id or record.result != "pending":
                continue
            updated = RunControlRecord(
                run_id=record.run_id,
                action=record.action,
                actor=record.actor,
                reason=record.reason,
                requested_at=record.requested_at,
                resolved_at=utc_now_iso(),
                result=result,
            )
            records[index] = updated
            self._write(records)
            return updated
        raise KeyError(f"no pending control request for run: {run_id}")

    def _write(self, records: list[RunControlRecord]) -> None:
        _write_store(self.path, [asdict(record) for record in records])
