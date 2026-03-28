from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .bus import MessageBus
from .envelopes import MessageEnvelope, create_envelope_id, utc_now_iso
from .runner import RunnerResult, TurnRunner
from .work import _read_store, _write_store


@dataclass(slots=True)
class GatewaySession:
    gateway_session_id: str
    source: str
    target_agent: str
    thread_key: str
    mode: str
    model: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        self.gateway_session_id = self.gateway_session_id.strip()
        self.source = self.source.strip()
        self.target_agent = self.target_agent.strip()
        self.thread_key = self.thread_key.strip()
        self.mode = self.mode.strip()
        self.model = self.model.strip()
        if not self.gateway_session_id:
            raise ValueError("gateway_session_id cannot be empty")
        if not self.source:
            raise ValueError("source cannot be empty")
        if not self.target_agent:
            raise ValueError("target_agent cannot be empty")
        if not self.thread_key:
            raise ValueError("thread_key cannot be empty")

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> "GatewaySession":
        payload = dict(raw)
        payload.setdefault("mode", "default")
        payload.setdefault("model", "")
        return cls(**payload)


class GatewaySessionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "gateway_sessions.json"

    def create(
        self,
        *,
        source: str,
        target_agent: str,
        thread_key: str | None = None,
        mode: str = "default",
        model: str = "",
    ) -> GatewaySession:
        now = utc_now_iso()
        gateway_session_id = create_envelope_id("gws")
        record = GatewaySession(
            gateway_session_id=gateway_session_id,
            source=source,
            target_agent=target_agent,
            thread_key=thread_key or f"gateway:{gateway_session_id}",
            mode=mode,
            model=model,
            created_at=now,
            updated_at=now,
        )
        records = self.list()
        records.append(record)
        self._write(records)
        return record

    def get(self, gateway_session_id: str) -> GatewaySession | None:
        for record in self.list():
            if record.gateway_session_id == gateway_session_id:
                return record
        return None

    def list(self) -> list[GatewaySession]:
        return [GatewaySession.from_json_dict(raw) for raw in _read_store(self.path)]

    def update(
        self,
        gateway_session_id: str,
        *,
        mode: str | None = None,
        model: str | None = None,
    ) -> GatewaySession:
        records = self.list()
        for index, record in enumerate(records):
            if record.gateway_session_id != gateway_session_id:
                continue
            updated = GatewaySession(
                gateway_session_id=record.gateway_session_id,
                source=record.source,
                target_agent=record.target_agent,
                thread_key=record.thread_key,
                mode=record.mode if mode is None else mode.strip(),
                model=record.model if model is None else model.strip(),
                created_at=record.created_at,
                updated_at=utc_now_iso(),
            )
            records[index] = updated
            self._write(records)
            return updated
        raise KeyError(f"unknown gateway session: {gateway_session_id}")

    def _write(self, records: list[GatewaySession]) -> None:
        _write_store(self.path, [asdict(record) for record in records])


@dataclass(slots=True)
class GatewayTurnResult:
    gateway_session: GatewaySession
    runner_result: RunnerResult


class GatewayService:
    def __init__(
        self,
        *,
        sessions: GatewaySessionStore,
        runner: TurnRunner,
        bus: MessageBus,
    ) -> None:
        self.sessions = sessions
        self.runner = runner
        self.bus = bus

    def open_session(
        self,
        *,
        source: str,
        target_agent: str = "superagent",
        thread_key: str | None = None,
        mode: str = "default",
        model: str = "",
    ) -> GatewaySession:
        return self.sessions.create(
            source=source,
            target_agent=target_agent,
            thread_key=thread_key,
            mode=mode,
            model=model,
        )

    def get_session(self, gateway_session_id: str) -> GatewaySession | None:
        return self.sessions.get(gateway_session_id)

    def set_session_mode(self, gateway_session_id: str, mode: str) -> GatewaySession:
        return self.sessions.update(gateway_session_id, mode=mode)

    def set_session_model(self, gateway_session_id: str, model: str) -> GatewaySession:
        return self.sessions.update(gateway_session_id, model=model)

    async def send_user_message(
        self,
        gateway_session_id: str,
        content: str,
    ) -> GatewayTurnResult:
        session = self.sessions.get(gateway_session_id)
        if session is None:
            raise KeyError(f"unknown gateway session: {gateway_session_id}")
        envelope = MessageEnvelope(
            source=session.source,
            target_agent=session.target_agent,
            thread_key=session.thread_key,
            kind="user_message",
            content=content,
            metadata={
                "gateway_session_id": session.gateway_session_id,
                "mode": session.mode,
                "model": session.model,
            },
        )
        await self.bus.publish_inbound(envelope)
        result = await self.runner.run_from_bus()
        return GatewayTurnResult(
            gateway_session=self.sessions.get(gateway_session_id) or session,
            runner_result=result,
        )
