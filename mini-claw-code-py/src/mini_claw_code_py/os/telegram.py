from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..providers import OpenRouterProvider
from ..tools import UserInputRequest
from .agent_registry import HostedAgentFactory, HostedAgentRegistry
from .bus import MessageBus
from .channels import ChannelRegistry
from .gateway import GatewayService, GatewaySession, GatewaySessionStore
from .runner import TurnRunner
from .session_router import SessionRouter
from .work import GoalStore, RunStore, SessionWorkStore, TaskStore, TeamRegistry, default_os_state_root
from ..session import SessionStore
from .session_router import default_route_store


@dataclass(slots=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    text: str
    message_id: int


class TelegramBotClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self._http_client = http_client
        if not self.token:
            raise ValueError("telegram bot token cannot be empty")

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[TelegramUpdate]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = await self._request("getUpdates", payload)
        updates: list[TelegramUpdate] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if not isinstance(message, dict):
                continue
            text = message.get("text")
            chat = message.get("chat")
            if not isinstance(text, str) or not isinstance(chat, dict):
                continue
            chat_id = chat.get("id")
            message_id = message.get("message_id")
            update_id = item.get("update_id")
            if not isinstance(chat_id, int) or not isinstance(message_id, int) or not isinstance(update_id, int):
                continue
            updates.append(
                TelegramUpdate(
                    update_id=update_id,
                    chat_id=chat_id,
                    text=text,
                    message_id=message_id,
                )
            )
        return updates

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        await self._request("sendMessage", payload)

    async def _request(self, method: str, payload: dict[str, Any]) -> Any:
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        try:
            response = await client.post(f"{self.base_url}/bot{self.token}/{method}", json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("ok") is not True:
                raise ValueError(f"telegram api {method} failed: {data}")
            return data.get("result")
        finally:
            if owns_client:
                await client.aclose()


class TelegramOffsetStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "telegram_offsets.json"

    def get(self, channel_name: str) -> int | None:
        raw = self._read()
        value = raw.get(channel_name)
        return value if isinstance(value, int) else None

    def update(self, channel_name: str, update_id: int) -> None:
        raw = self._read()
        raw[channel_name] = update_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(_json_dumps(raw)), encoding="utf-8")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        import json

        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}


def _json_dumps(raw: dict[str, Any]) -> str:
    import json

    return json.dumps(raw, indent=2, ensure_ascii=True) + "\n"


class TelegramChannelRuntime:
    def __init__(
        self,
        *,
        channel_name: str,
        bot: TelegramBotClient,
        gateway: GatewayService,
        gateway_sessions: GatewaySessionStore,
        channels: ChannelRegistry,
        teams: TeamRegistry,
        offset_store: TelegramOffsetStore,
    ) -> None:
        self.channel_name = channel_name.strip()
        self.bot = bot
        self.gateway = gateway
        self.gateway_sessions = gateway_sessions
        self.channels = channels
        self.teams = teams
        self.offset_store = offset_store
        if not self.channel_name:
            raise ValueError("channel_name cannot be empty")

    async def run_once(self, *, timeout: int = 30) -> int:
        last_seen = self.offset_store.get(self.channel_name)
        updates = await self.bot.get_updates(offset=None if last_seen is None else last_seen + 1, timeout=timeout)
        handled = 0
        for update in updates:
            await self.handle_update(update)
            self.offset_store.update(self.channel_name, update.update_id)
            handled += 1
        return handled

    async def run_forever(self, *, timeout: int = 30, idle_sleep_seconds: float = 1.0) -> None:
        while True:
            handled = await self.run_once(timeout=timeout)
            if handled == 0:
                await asyncio.sleep(idle_sleep_seconds)

    async def handle_update(self, update: TelegramUpdate) -> GatewaySession:
        channel = self.channels.require(self.channel_name)
        target_agent = channel.resolve_target_agent(self.teams)
        thread_key = channel.resolve_thread_key(str(update.chat_id))
        session = self._resolve_or_create_session(
            source=f"telegram:{self.channel_name}",
            target_agent=target_agent,
            thread_key=thread_key,
        )
        result = await self.gateway.send_user_message(session.gateway_session_id, update.text)
        reply = (result.runner_result.reply_text or "").strip()
        if reply:
            for chunk in _chunk_telegram_text(reply):
                await self.bot.send_message(chat_id=update.chat_id, text=chunk, reply_to_message_id=update.message_id)
        return session

    def _resolve_or_create_session(self, *, source: str, target_agent: str, thread_key: str) -> GatewaySession:
        for session in self.gateway_sessions.list():
            if session.source == source and session.target_agent == target_agent and session.thread_key == thread_key:
                return session
        return self.gateway.open_session(
            source=source,
            target_agent=target_agent,
            thread_key=thread_key,
        )


def _chunk_telegram_text(text: str, *, limit: int = 4000) -> list[str]:
    normalized = text.strip()
    if len(normalized) <= limit:
        return [normalized]
    chunks: list[str] = []
    remaining = normalized
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return [chunk for chunk in chunks if chunk]


def build_telegram_runtime(
    *,
    cwd: Path,
    token: str,
    channel_name: str = "telegram",
    home: Path | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> TelegramChannelRuntime:
    target_home = Path.home() if home is None else Path(home)
    provider = OpenRouterProvider.from_env()
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    sessions = SessionStore(cwd / ".mini-claw" / "sessions")
    os_root = default_os_state_root(cwd)
    gateway_sessions = GatewaySessionStore(os_root)
    registry = HostedAgentRegistry.discover_default(cwd=cwd, home=target_home)
    teams = TeamRegistry.discover_default(cwd=cwd, home=target_home)
    bus = MessageBus()
    runner = TurnRunner(
        registry=registry,
        factory=HostedAgentFactory(
            provider=provider,
            home=target_home,
            input_queue=input_queue,
        ),
        router=SessionRouter(default_route_store(cwd), sessions),
        sessions=sessions,
        runs=RunStore(os_root),
        teams=teams,
        goals=GoalStore(os_root),
        tasks=TaskStore(os_root),
        session_work=SessionWorkStore(os_root),
        bus=bus,
    )
    gateway = GatewayService(
        sessions=gateway_sessions,
        runner=runner,
        bus=bus,
    )
    return TelegramChannelRuntime(
        channel_name=channel_name,
        bot=TelegramBotClient(token, http_client=http_client),
        gateway=gateway,
        gateway_sessions=gateway_sessions,
        channels=ChannelRegistry.discover_default(cwd=cwd, home=target_home),
        teams=teams,
        offset_store=TelegramOffsetStore(os_root),
    )


def parse_telegram_runtime_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Telegram Agent OS channel runtime.")
    parser.add_argument("--channel", default="telegram", help="channel name in .channels.json")
    parser.add_argument("--token", required=True, help="Telegram bot token")
    parser.add_argument("--cwd", default=".", help="workspace root")
    parser.add_argument("--poll-timeout", type=int, default=30, help="getUpdates long-poll timeout in seconds")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="sleep time after empty polls")
    return parser.parse_args(argv)


async def run_telegram_runtime_from_args(argv: list[str] | None = None) -> None:
    args = parse_telegram_runtime_args(argv)
    runtime = build_telegram_runtime(
        cwd=Path(args.cwd).expanduser().resolve(),
        token=args.token,
        channel_name=args.channel,
    )
    await runtime.run_forever(timeout=args.poll_timeout, idle_sleep_seconds=args.idle_sleep)
