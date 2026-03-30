import asyncio
from collections import deque
from pathlib import Path

from mini_claw_code_py import (
    CHANNEL_CONFIG_FILE_NAME,
    TEAM_CONFIG_FILE_NAME,
    ChannelRegistry,
    GatewayService,
    GatewaySessionStore,
    GoalStore,
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageBus,
    MockStreamProvider,
    RunStore,
    SessionRouter,
    SessionStore,
    SessionWorkStore,
    TeamRegistry,
    StopReason,
    TaskStore,
    TurnRunner,
    default_channel_config_paths,
    default_os_state_root,
    default_route_store,
    parse_channel_registry,
)
from mini_claw_code_py.os.telegram import TelegramBotClient, TelegramChannelRuntime, TelegramOffsetStore, TelegramUpdate
from mini_claw_code_py.tui.app import resolve_cli_route
from mini_claw_code_py.tools import UserInputRequest
from mini_claw_code_py.types import AssistantTurn


def test_ch44_default_channel_config_paths_follow_user_then_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / CHANNEL_CONFIG_FILE_NAME).write_text('{"channels": {}}\n', encoding="utf-8")
    (project / CHANNEL_CONFIG_FILE_NAME).write_text('{"channels": {}}\n', encoding="utf-8")

    paths = default_channel_config_paths(cwd=project, home=home)

    assert paths == [
        (home / CHANNEL_CONFIG_FILE_NAME).resolve(),
        (project / CHANNEL_CONFIG_FILE_NAME).resolve(),
    ]


def test_ch44_channel_registry_discovers_default_cli_channel_when_no_files_exist(tmp_path: Path) -> None:
    registry = ChannelRegistry.discover_default(cwd=tmp_path / "project", home=tmp_path / "home")

    channel = registry.require("cli")
    assert channel.default_target_agent == "superagent"
    assert channel.resolve_thread_key("local") == "cli:local"


def test_ch44_channel_registry_merges_user_and_project_fields(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "cli": {\n'
            '      "description": "General terminal front door.",\n'
            '      "default_target_agent": "superagent",\n'
            '      "thread_prefix": "terminal"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (project / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "cli": {\n'
            '      "description": "Project terminal front door."\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    registry = ChannelRegistry.discover_default(cwd=project, home=home)
    cli = registry.require("cli")

    assert cli.description == "Project terminal front door."
    assert cli.default_target_agent == "superagent"
    assert cli.thread_prefix == "terminal"


def test_ch44_parse_channel_registry_reads_explicit_channel_file(tmp_path: Path) -> None:
    config_path = tmp_path / CHANNEL_CONFIG_FILE_NAME
    config_path.write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "telegram": {\n'
            '      "description": "Telegram front door.",\n'
            '      "default_target_agent": "support-agent",\n'
            '      "thread_prefix": "tg"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    parsed = parse_channel_registry(config_path)

    assert parsed["telegram"].default_target_agent == "support-agent"
    assert parsed["telegram"].resolve_thread_key("123") == "tg:123"


def test_ch44_cli_route_can_resolve_target_agent_from_default_team(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (project / TEAM_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "support": {\n'
            '      "description": "Support team.",\n'
            '      "lead_agent": "support-lead",\n'
            '      "member_agents": ["support-lead", "triage-bot"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (project / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "cli": {\n'
            '      "description": "Support terminal front door.",\n'
            '      "default_team": "support",\n'
            '      "thread_prefix": "cli"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    teams = TeamRegistry.discover_default(cwd=project, home=home)
    _, target_agent, thread_key = resolve_cli_route(cwd=project, home=home, teams=teams)

    assert target_agent == "support-lead"
    assert thread_key == "cli:local"


def test_ch44_team_registry_reads_workspace_root_and_renders_it(tmp_path: Path) -> None:
    config_path = tmp_path / TEAM_CONFIG_FILE_NAME
    config_path.write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "marketing": {\n'
            '      "description": "Marketing team.",\n'
            '      "lead_agent": "marketing-lead",\n'
            '      "member_agents": ["copywriter", "seo-agent"],\n'
            '      "workspace_root": "workspaces/marketing"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    registry = TeamRegistry.discover([config_path])
    team = registry.require("marketing")

    assert team.workspace_root == (tmp_path / "workspaces" / "marketing").resolve()
    assert str(team.workspace_root) in registry.render()


def test_ch44_telegram_bot_client_parses_updates_and_sends_messages() -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    def handler(request):  # type: ignore[no-untyped-def]
        import json

        requests.append((str(request.url), {} if request.content == b"" else json.loads(request.content.decode("utf-8"))))
        if request.url.path.endswith("/getUpdates"):
            return __import__("httpx").Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {
                            "update_id": 101,
                            "message": {
                                "message_id": 55,
                                "text": "hello",
                                "chat": {"id": 999},
                            },
                        }
                    ],
                },
            )
        return __import__("httpx").Response(200, json={"ok": True, "result": {"message_id": 56}})

    import httpx

    client = TelegramBotClient(
        "token",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def run() -> list[TelegramUpdate]:
        updates = await client.get_updates(offset=50, timeout=3)
        await client.send_message(chat_id=999, text="reply", reply_to_message_id=55)
        return updates

    updates = asyncio.run(run())

    assert updates[0].update_id == 101
    assert updates[0].chat_id == 999
    assert any(url.endswith("/getUpdates") for url, _ in requests)
    assert any(url.endswith("/sendMessage") for url, _ in requests)


def test_ch44_telegram_runtime_routes_updates_through_gateway_and_reuses_session(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "telegram": {\n'
            '      "description": "Telegram front door.",\n'
            '      "default_team": "support",\n'
            '      "thread_prefix": "tg"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / TEAM_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "support": {\n'
            '      "description": "Support team.",\n'
            '      "lead_agent": "support-lead",\n'
            '      "member_agents": ["support-lead"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".agents.json").write_text(
        (
            '{\n'
            '  "agents": {\n'
            '    "support-lead": {\n'
            '      "description": "Support lead.",\n'
            '      "workspace_root": ".",\n'
            '      "default_channels": ["telegram"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="Hello from Telegram.", tool_calls=[], stop_reason=StopReason.STOP),
                AssistantTurn(text="Second reply.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    sessions = SessionStore(tmp_path / ".mini-claw" / "sessions")
    os_root = default_os_state_root(tmp_path)
    bus = MessageBus()
    runner = TurnRunner(
        registry=HostedAgentRegistry.discover_default(cwd=tmp_path, home=home),
        factory=HostedAgentFactory(
            provider=provider,  # type: ignore[arg-type]
            home=home,
            input_queue=input_queue,
        ),
        router=SessionRouter(default_route_store(tmp_path), sessions),
        sessions=sessions,
        runs=RunStore(os_root),
        teams=TeamRegistry.discover_default(cwd=tmp_path, home=home),
        goals=GoalStore(os_root),
        tasks=TaskStore(os_root),
        session_work=SessionWorkStore(os_root),
        bus=bus,
    )
    gateway_sessions = GatewaySessionStore(os_root)
    gateway = GatewayService(
        sessions=gateway_sessions,
        runner=runner,
        bus=bus,
    )

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str, int | None]] = []

        async def get_updates(self, *, offset: int | None = None, timeout: int = 30) -> list[TelegramUpdate]:
            raise AssertionError("not used in this test")

        async def send_message(self, *, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
            self.sent.append((chat_id, text, reply_to_message_id))

    bot = FakeBot()
    runtime = TelegramChannelRuntime(
        channel_name="telegram",
        bot=bot,  # type: ignore[arg-type]
        gateway=gateway,
        gateway_sessions=gateway_sessions,
        channels=ChannelRegistry.discover_default(cwd=tmp_path, home=home),
        teams=TeamRegistry.discover_default(cwd=tmp_path, home=home),
        offset_store=TelegramOffsetStore(os_root),
    )

    async def run() -> list[str]:
        await runtime.handle_update(TelegramUpdate(update_id=1, chat_id=42, text="hello", message_id=10))
        await runtime.handle_update(TelegramUpdate(update_id=2, chat_id=42, text="again", message_id=11))
        return [session.gateway_session_id for session in gateway_sessions.list()]

    session_ids = asyncio.run(run())

    assert len(session_ids) == 1
    assert bot.sent[0][1] == "Hello from Telegram."
    assert bot.sent[1][1] == "Second reply."
    assert bot.sent[0][0] == 42
    assert gateway_sessions.list()[0].thread_key == "tg:42"
