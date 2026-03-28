import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mini_claw_code_py import (
    CronService,
    CronStore,
    GoalStore,
    HeartbeatService,
    HostedAgentFactory,
    HostedAgentRegistry,
    MessageBus,
    MockStreamProvider,
    RunStore,
    SessionRouter,
    SessionStore,
    SessionWorkStore,
    StopReason,
    TaskStore,
    TeamRegistry,
    TurnRunner,
    UserInputRequest,
    default_os_state_root,
    default_route_store,
    heartbeat_has_actionable_work,
)
from mini_claw_code_py.types import AssistantTurn


def _build_runner(
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


def test_ch43_heartbeat_detects_actionable_work(tmp_path: Path) -> None:
    heartbeat = tmp_path / "HEARTBEAT.md"
    heartbeat.write_text(
        "# Heartbeat\n\n- [x] done already\n\nReview unresolved deployment notes.\n",
        encoding="utf-8",
    )

    assert heartbeat_has_actionable_work(heartbeat) is True

    heartbeat.write_text("# Heartbeat\n\n- [x] done already\n", encoding="utf-8")

    assert heartbeat_has_actionable_work(heartbeat) is False


def test_ch43_cron_store_tracks_due_jobs_and_reschedules_every_jobs(tmp_path: Path) -> None:
    store = CronStore(default_os_state_root(tmp_path))
    now = datetime(2026, 3, 29, 10, 0, tzinfo=UTC)

    every_job = store.create_every(
        name="Daily review",
        content="Check pending goals.",
        every_seconds=60,
        target_agent="superagent",
        now=now,
    )
    at_job = store.create_at(
        name="One-shot reminder",
        content="Review the release board.",
        run_at=(now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        target_agent="superagent",
        now=now,
    )

    due = store.due(now=now + timedelta(seconds=61))

    assert {job.job_id for job in due} == {every_job.job_id, at_job.job_id}

    rescheduled = store.mark_ran(every_job.job_id, now=now + timedelta(seconds=61))
    completed_once = store.mark_ran(at_job.job_id, now=now + timedelta(seconds=61))

    assert rescheduled.enabled is True
    assert completed_once.enabled is False
    assert store.get(every_job.job_id).next_run_at > every_job.next_run_at


def test_ch43_heartbeat_service_publishes_background_envelope_for_team_lead(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    (tmp_path / ".teams.json").write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "product-a": {\n'
            '      "description": "Delivery team.",\n'
            '      "lead_agent": "superagent",\n'
            '      "member_agents": ["backend-dev"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "HEARTBEAT.md").write_text("Investigate the deployment warning.\n", encoding="utf-8")
    bus = MessageBus()
    service = HeartbeatService(
        cwd=tmp_path,
        bus=bus,
        teams=TeamRegistry.discover_default(cwd=tmp_path, home=tmp_path / "home"),
    )

    async def run() -> tuple[object | None, object]:
        envelope = await service.trigger(target_team="product-a")
        event = await bus.consume_event()
        return envelope, event

    envelope, event = asyncio.run(run())

    assert envelope is not None
    assert envelope.kind == "background_message"
    assert envelope.source == "heartbeat"
    assert envelope.target_agent == "superagent"
    assert envelope.thread_key == "system:heartbeat"
    assert event.payload["service"] == "heartbeat"


def test_ch43_background_turns_can_run_end_to_end_via_bus_and_runner(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    (tmp_path / "HEARTBEAT.md").write_text("Review the pending delivery task.\n", encoding="utf-8")
    bus = MessageBus()
    provider = MockStreamProvider(
        deque([AssistantTurn(text="HEARTBEAT_OK", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    runner = _build_runner(tmp_path, provider=provider, bus=bus)
    service = HeartbeatService(cwd=tmp_path, bus=bus)

    async def run() -> tuple[object | None, object, object]:
        envelope = await service.trigger(target_agent="superagent")
        result = await runner.run_from_bus()
        outbound = await bus.consume_outbound()
        return envelope, result, outbound

    envelope, result, outbound = asyncio.run(run())

    assert envelope is not None
    assert result.reply_text == "HEARTBEAT_OK"
    assert result.context.envelope.kind == "background_message"
    assert result.context.run.source == "heartbeat"
    assert result.context.run.thread_key == "system:heartbeat"
    assert outbound.parent_run_id == result.context.run.run_id


def test_ch43_cron_service_publishes_due_jobs_and_runner_handles_them(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    bus = MessageBus()
    provider = MockStreamProvider(
        deque([AssistantTurn(text="Cron handled.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    runner = _build_runner(tmp_path, provider=provider, bus=bus)
    store = CronStore(default_os_state_root(tmp_path))
    now = datetime(2026, 3, 29, 10, 0, tzinfo=UTC)
    job = store.create_at(
        name="Release reminder",
        content="Review the release candidate.",
        run_at=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        target_agent="superagent",
        now=now - timedelta(seconds=60),
    )
    service = CronService(store=store, bus=bus)

    async def run() -> tuple[list[object], object]:
        published = await service.fire_due(now=now)
        result = await runner.run_from_bus()
        return published, result

    published, result = asyncio.run(run())

    assert len(published) == 1
    assert published[0].metadata["cron_job_id"] == job.job_id
    assert published[0].source == f"cron:{job.job_id}"
    assert result.reply_text == "Cron handled."
    assert result.context.envelope.kind == "background_message"
    assert store.get(job.job_id).enabled is False
