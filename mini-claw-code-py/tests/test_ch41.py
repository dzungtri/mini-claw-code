import asyncio
from collections import deque
from pathlib import Path

from mini_claw_code_py import (
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageBus,
    MessageEnvelope,
    MockStreamProvider,
    RunStore,
    SessionRouter,
    SessionStore,
    StopReason,
    TurnRunner,
    default_os_state_root,
    default_route_store,
)
from mini_claw_code_py.tools import UserInputRequest
from mini_claw_code_py.types import AssistantTurn


def _build_runner(
    root: Path,
    *,
    provider: MockStreamProvider,
    bus: MessageBus | None = None,
) -> TurnRunner:
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    sessions = SessionStore(root / ".mini-claw" / "sessions")
    return TurnRunner(
        registry=HostedAgentRegistry.discover_default(cwd=root, home=root / "home"),
        factory=HostedAgentFactory(
            provider=provider,  # type: ignore[arg-type]
            home=root / "home",
            input_queue=input_queue,
        ),
        router=SessionRouter(default_route_store(root), sessions),
        sessions=sessions,
        runs=RunStore(default_os_state_root(root)),
        bus=bus,
    )


def test_ch41_turn_runner_executes_one_envelope_and_persists_run_and_session(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Hello from the runner.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    runner = _build_runner(tmp_path, provider=provider)

    result = asyncio.run(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="Say hello.",
            )
        )
    )

    assert result.reply_text == "Hello from the runner."
    assert result.context.route.session_id == result.context.session.id
    assert result.outbound.source == "superagent"
    assert result.outbound.target_agent == "cli"
    assert result.outbound.parent_run_id == result.context.run.run_id
    assert result.context.run.status == "completed"
    assert (default_os_state_root(tmp_path) / "runs.json").exists()
    assert (tmp_path / ".mini-claw" / "sessions" / result.context.session.id / "session.json").exists()


def test_ch41_turn_runner_reuses_routed_session_across_turns(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="First reply.", tool_calls=[], stop_reason=StopReason.STOP),
                AssistantTurn(text="Second reply.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    runner = _build_runner(tmp_path, provider=provider)

    first = asyncio.run(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="First turn.",
            )
        )
    )
    second = asyncio.run(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="Second turn.",
            )
        )
    )

    assert second.context.session.id == first.context.session.id
    assert len(second.history) > len(first.history)


def test_ch41_turn_runner_publishes_bus_events_and_outbound_message(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="Done.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    bus = MessageBus()
    runner = _build_runner(tmp_path, provider=provider, bus=bus)
    envelope = MessageEnvelope(
        source="cli",
        target_agent="superagent",
        thread_key="cli:local",
        kind="user_message",
        content="Do the work.",
        trace_id="trace_demo",
        metadata={"task_id": "task_demo"},
    )

    async def run() -> tuple[object, object, object, object, object]:
        result = await runner.run(envelope)
        outbound = await bus.consume_outbound()
        event_one = await bus.consume_event()
        event_two = await bus.consume_event()
        event_three = await bus.consume_event()
        return result, outbound, event_one, event_two, event_three

    result, outbound, event_one, event_two, event_three = asyncio.run(run())

    assert result.context.run.task_id == "task_demo"
    assert outbound.trace_id == "trace_demo"
    assert outbound.parent_run_id == result.context.run.run_id
    assert [event_one.kind, event_two.kind, event_three.kind] == [
        "run_started",
        "outbound_message",
        "run_finished",
    ]
