import asyncio
from collections import deque
from pathlib import Path

from mini_claw_code_py import (
    GatewayService,
    GatewaySessionStore,
    GoalStore,
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageBus,
    MessageEnvelope,
    MockStreamProvider,
    RunStore,
    SessionRouter,
    SessionStore,
    SessionWorkStore,
    StopReason,
    TaskStore,
    TeamRegistry,
    TurnRunner,
    default_os_state_root,
    default_route_store,
)
from mini_claw_code_py.tools import UserInputRequest
from mini_claw_code_py.types import AssistantTurn


def _build_gateway_runner(
    root: Path,
    *,
    provider: MockStreamProvider,
    bus: MessageBus,
) -> TurnRunner:
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    sessions = SessionStore(root / ".mini-claw" / "sessions")
    os_root = default_os_state_root(root)
    return TurnRunner(
        registry=HostedAgentRegistry.discover_default(cwd=root, home=root / "home"),
        factory=HostedAgentFactory(
            provider=provider,  # type: ignore[arg-type]
            home=root / "home",
            input_queue=input_queue,
        ),
        router=SessionRouter(default_route_store(root), sessions),
        sessions=sessions,
        runs=RunStore(os_root),
        teams=TeamRegistry.discover_default(cwd=root, home=root / "home"),
        goals=GoalStore(os_root),
        tasks=TaskStore(os_root),
        session_work=SessionWorkStore(os_root),
        bus=bus,
    )


def test_ch42_gateway_session_store_creates_and_updates_sessions(tmp_path: Path) -> None:
    store = GatewaySessionStore(tmp_path / ".mini-claw" / "os")

    session = store.create(source="zed", target_agent="superagent", mode="plan", model="gpt-5")
    updated = store.update(session.gateway_session_id, mode="execute", model="gemini-2.5")

    assert session.gateway_session_id.startswith("gws_")
    assert session.thread_key.startswith("gateway:")
    assert updated.mode == "execute"
    assert updated.model == "gemini-2.5"
    assert store.get(session.gateway_session_id) == updated


def test_ch42_gateway_service_runs_messages_through_bus_and_runner(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    bus = MessageBus()
    provider = MockStreamProvider(
        deque([AssistantTurn(text="Hello from gateway.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    runner = _build_gateway_runner(tmp_path, provider=provider, bus=bus)
    service = GatewayService(
        sessions=GatewaySessionStore(default_os_state_root(tmp_path)),
        runner=runner,
        bus=bus,
    )

    async def run() -> tuple[object, object]:
        gateway_session = service.open_session(source="zed", target_agent="superagent", mode="review", model="gpt-5")
        result = await service.send_user_message(gateway_session.gateway_session_id, "Review this repository.")
        outbound = await bus.consume_outbound()
        return result, outbound

    result, outbound = asyncio.run(run())

    assert result.gateway_session.mode == "review"
    assert result.runner_result.reply_text == "Hello from gateway."
    assert result.runner_result.context.envelope.metadata["gateway_session_id"] == result.gateway_session.gateway_session_id
    assert result.runner_result.context.envelope.metadata["mode"] == "review"
    assert result.runner_result.context.envelope.metadata["model"] == "gpt-5"
    assert result.runner_result.context.run.source == "zed"
    assert outbound.parent_run_id == result.runner_result.context.run.run_id


def test_ch42_gateway_service_reuses_routed_harness_session_across_messages(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    bus = MessageBus()
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="First.", tool_calls=[], stop_reason=StopReason.STOP),
                AssistantTurn(text="Second.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    runner = _build_gateway_runner(tmp_path, provider=provider, bus=bus)
    service = GatewayService(
        sessions=GatewaySessionStore(default_os_state_root(tmp_path)),
        runner=runner,
        bus=bus,
    )

    async def run() -> tuple[object, object]:
        gateway_session = service.open_session(source="zed", target_agent="superagent")
        first = await service.send_user_message(gateway_session.gateway_session_id, "First prompt.")
        second = await service.send_user_message(gateway_session.gateway_session_id, "Second prompt.")
        return first, second

    first, second = asyncio.run(run())

    assert first.gateway_session.gateway_session_id == second.gateway_session.gateway_session_id
    assert first.runner_result.context.session.id == second.runner_result.context.session.id
    assert first.runner_result.context.run.task_id == second.runner_result.context.run.task_id
