import asyncio
from collections import deque
from pathlib import Path

from mini_claw_code_py import (
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageEnvelope,
    MockStreamProvider,
    OperatorEventRecord,
    OperatorEventStore,
    OperatorService,
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


def _build_runner(root: Path) -> TurnRunner:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(text="Hello.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
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
    )


def test_ch46_operator_event_store_is_append_only_and_filterable(tmp_path: Path) -> None:
    store = OperatorEventStore(default_os_state_root(tmp_path))
    first = store.append(
        OperatorEventRecord.create(
            kind="run_started",
            trace_id="trace_a",
            run_id="run_a",
            session_id="sess_a",
            target_agent="superagent",
            payload={"status": "running"},
        )
    )
    second = store.append(
        OperatorEventRecord.create(
            kind="run_finished",
            trace_id="trace_b",
            run_id="run_b",
            session_id="sess_b",
            target_agent="superagent",
            payload={"status": "completed"},
        )
    )

    assert store.list(limit=10) == [first, second]
    assert store.list(run_id="run_a", limit=10) == [first]
    assert "run_started" in store.render_for_run("run_a")


def test_ch46_turn_runner_persists_operator_event_timeline_and_service_can_read_it(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    runner = _build_runner(tmp_path)

    result = asyncio.run(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="Hello",
            )
        )
    )

    store = OperatorEventStore(default_os_state_root(tmp_path))
    events = store.list(run_id=result.context.run.run_id, limit=20)
    kinds = [event.kind for event in events]

    assert "run_started" in kinds
    assert "outbound_message" in kinds
    assert "run_finished" in kinds

    service = OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home")
    service_events = service.inspect_run_events(result.context.run.run_id)

    assert [event.kind for event in service_events] == kinds
