import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageBus,
    MessageEnvelope,
    MockStreamProvider,
    GoalStore,
    RunStore,
    SessionWorkStore,
    SessionRouter,
    SessionStore,
    StopReason,
    TaskStore,
    TeamRegistry,
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


def test_ch41_turn_runner_executes_one_envelope_and_persists_run_and_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("MINI_CLAW_INPUT_COST_PER_MILLION_USD", "3")
    monkeypatch.setenv("MINI_CLAW_OUTPUT_COST_PER_MILLION_USD", "5")
    monkeypatch.setenv("MINI_CLAW_PRICING_KEY", "test/openrouter")
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
    assert result.context.run.source == "cli"
    assert result.context.run.thread_key == "cli:local"
    assert result.context.run.total_tokens > 0
    assert result.context.run.estimated_total_cost_usd > 0
    assert result.context.run.pricing_key == "test/openrouter"
    assert result.context.run.estimated_input_cost_usd == pytest.approx(
        result.context.run.prompt_tokens * 3 / 1_000_000
    )
    assert result.context.run.estimated_output_cost_usd == pytest.approx(
        result.context.run.completion_tokens * 5 / 1_000_000
    )
    assert result.context.run.estimated_total_cost_usd == pytest.approx(
        result.context.run.estimated_input_cost_usd + result.context.run.estimated_output_cost_usd
    )
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


def test_ch41_turn_runner_creates_session_work_binding_for_frontdoor_session(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque([AssistantTurn(text="First reply.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    runner = _build_runner(tmp_path, provider=provider)

    result = asyncio.run(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="Build the release candidate.",
            )
        )
    )

    os_root = default_os_state_root(tmp_path)
    work = SessionWorkStore(os_root).get(result.context.session.id)
    task = TaskStore(os_root).get(result.context.run.task_id or "")
    goal = GoalStore(os_root).get(work.goal_id if work is not None else "")

    assert work is not None
    assert result.context.run.task_id == work.task_id
    assert task is not None
    assert task.status == "in_progress"
    assert goal is not None
    assert goal.status == "in_progress"


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


def test_ch41_turn_runner_can_consume_directly_from_bus(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="Bus path reply.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    bus = MessageBus()
    runner = _build_runner(tmp_path, provider=provider, bus=bus)
    envelope = MessageEnvelope(
        source="gateway",
        target_agent="superagent",
        thread_key="gateway:demo",
        kind="user_message",
        content="Handle this through the bus.",
        trace_id="trace_bus_demo",
        metadata={"mode": "review", "model": "gpt-5"},
    )

    async def run() -> tuple[object, object]:
        await bus.publish_inbound(envelope)
        result = await runner.run_from_bus()
        outbound = await bus.consume_outbound()
        return result, outbound

    result, outbound = asyncio.run(run())

    assert result.reply_text == "Bus path reply."
    assert result.context.envelope.trace_id == "trace_bus_demo"
    assert result.context.envelope.metadata["mode"] == "review"
    assert result.context.envelope.metadata["model"] == "gpt-5"
    assert result.context.run.source == "gateway"
    assert result.context.run.thread_key == "gateway:demo"
    assert outbound.trace_id == "trace_bus_demo"
    assert outbound.parent_run_id == result.context.run.run_id
