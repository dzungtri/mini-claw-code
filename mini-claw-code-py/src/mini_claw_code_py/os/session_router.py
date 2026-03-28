from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..session import SessionRecord, SessionStore
from .envelopes import utc_now_iso
from .work import default_os_state_root


@dataclass(slots=True)
class SessionRoute:
    target_agent: str
    thread_key: str
    session_id: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        self.target_agent = self.target_agent.strip()
        self.thread_key = self.thread_key.strip()
        self.session_id = self.session_id.strip()
        if not self.target_agent:
            raise ValueError("target_agent cannot be empty")
        if not self.thread_key:
            raise ValueError("thread_key cannot be empty")
        if not self.session_id:
            raise ValueError("session_id cannot be empty")

    @classmethod
    def from_json_dict(cls, raw: dict[str, str]) -> "SessionRoute":
        return cls(**raw)


class RouteStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "routes.json"

    def list(self) -> list[SessionRoute]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"route store must contain a JSON array: {self.path}")
        return [SessionRoute.from_json_dict(item) for item in raw if isinstance(item, dict)]

    def resolve(self, *, target_agent: str, thread_key: str) -> SessionRoute | None:
        for route in self.list():
            if route.target_agent == target_agent and route.thread_key == thread_key:
                return route
        return None

    def bind(self, *, target_agent: str, thread_key: str, session_id: str) -> SessionRoute:
        now = utc_now_iso()
        records = self.list()
        for index, route in enumerate(records):
            if route.target_agent != target_agent or route.thread_key != thread_key:
                continue
            updated = SessionRoute(
                target_agent=target_agent,
                thread_key=thread_key,
                session_id=session_id,
                created_at=route.created_at,
                updated_at=now,
            )
            records[index] = updated
            self._write(records)
            return updated
        created = SessionRoute(
            target_agent=target_agent,
            thread_key=thread_key,
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        records.append(created)
        self._write(records)
        return created

    def _write(self, routes: list[SessionRoute]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps([asdict(route) for route in routes], indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)


class SessionRouter:
    def __init__(self, routes: RouteStore, sessions: SessionStore) -> None:
        self.routes = routes
        self.sessions = sessions

    def resolve(self, *, target_agent: str, thread_key: str) -> SessionRoute | None:
        return self.routes.resolve(target_agent=target_agent, thread_key=thread_key)

    def bind(self, *, target_agent: str, thread_key: str, session_id: str) -> SessionRoute:
        return self.routes.bind(target_agent=target_agent, thread_key=thread_key, session_id=session_id)

    def resolve_or_create(
        self,
        *,
        target_agent: str,
        thread_key: str,
        cwd: Path,
    ) -> tuple[SessionRoute, SessionRecord]:
        route = self.resolve(target_agent=target_agent, thread_key=thread_key)
        if route is not None:
            try:
                return route, self.sessions.load(route.session_id)
            except FileNotFoundError:
                pass

        record = self.sessions.persist(self.sessions.create(cwd=cwd))
        route = self.bind(target_agent=target_agent, thread_key=thread_key, session_id=record.id)
        return route, record


def default_route_store(cwd: Path | None = None) -> RouteStore:
    return RouteStore(default_os_state_root(cwd))
