import asyncio
from collections import deque
from pathlib import Path

import pytest
from textual.widgets import Static

from mini_claw_code_py import (
    HostedAgentFactory,
    HostedAgentRegistry,
    AgentDone,
    AgentNotice,
    MessageEnvelope,
    MockStreamProvider,
    OperatorService,
    SessionRouter,
    SessionStore,
    RunControlStore,
    RunStore,
    StopReason,
    ToolCall,
    TurnRunner,
    WriteTodosTool,
    default_os_state_root,
    default_route_store,
)
from mini_claw_code_py.tools import UserInputRequest
from mini_claw_code_py.types import AssistantTurn

from mini_claw_code_py.ops.app import OperatorApp


def _build_runner(root: Path, *, provider: MockStreamProvider) -> TurnRunner:
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
    )


@pytest.mark.asyncio
async def test_ch48_runner_cancels_run_from_operator_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="call_todos",
                            name="write_todos",
                            arguments={"items": ["one task"]},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Should not complete normally.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    runner: TurnRunner = _build_runner(tmp_path, provider=provider)

    original_call = WriteTodosTool.call

    async def slow_call(self: WriteTodosTool, args: object) -> str:
        await asyncio.sleep(0.2)
        return await original_call(self, args)

    monkeypatch.setattr(WriteTodosTool, "call", slow_call)

    events: asyncio.Queue[object] = asyncio.Queue()
    worker = asyncio.create_task(
        runner.run(
            MessageEnvelope(
                source="cli",
                target_agent="superagent",
                thread_key="cli:local",
                kind="user_message",
                content="Start a task board.",
            ),
            events,
        )
    )

    runs = RunStore(default_os_state_root(tmp_path))
    run_id = ""
    for _ in range(40):
        records = runs.list()
        if records:
            run_id = records[-1].run_id
            break
        await asyncio.sleep(0.01)
    assert run_id

    service = OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home")
    assert service.cancel_run(run_id) == f"Cancellation requested for {run_id}."

    result = await worker

    assert result.reply_text == "Run cancelled by operator."
    assert result.context.run.status == "cancelled"

    latest_run = runs.get(run_id)
    assert latest_run is not None
    assert latest_run.status == "cancelled"

    controls = RunControlStore(default_os_state_root(tmp_path))
    control = controls.latest(run_id)
    assert control is not None
    assert control.result == "cancelled"

    observed: list[object] = []
    while not events.empty():
        observed.append(await events.get())
    assert any(isinstance(event, AgentNotice) and event.message == "Run cancelled by operator." for event in observed)
    assert any(isinstance(event, AgentDone) and event.text == "Run cancelled by operator." for event in observed)


def test_ch48_operator_service_cancel_completed_run_returns_status_message(
    tmp_path: Path,
) -> None:
    (tmp_path / "home").mkdir()
    provider = MockStreamProvider(
        deque([AssistantTurn(text="Done.", tool_calls=[], stop_reason=StopReason.STOP)])
    )
    runner = _build_runner(tmp_path, provider=provider)
    asyncio.run(
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

    service = OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home")
    run_id = service.list_runs(limit=1)[0].run_id
    assert service.cancel_run(run_id) == f"Run {run_id} is already completed."


@pytest.mark.asyncio
async def test_ch48_operator_app_cancel_command_updates_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("MINI_CLAW_INPUT_COST_PER_MILLION_USD", "3")
    monkeypatch.setenv("MINI_CLAW_OUTPUT_COST_PER_MILLION_USD", "5")
    runner = _build_runner(tmp_path, provider=MockStreamProvider(deque([AssistantTurn(text="Hello.", tool_calls=[], stop_reason=StopReason.STOP)])))
    result = await runner.run(
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="Hello",
        )
    )
    app = OperatorApp(OperatorService.discover_default(cwd=tmp_path, home=tmp_path / "home"))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/", "c", "a", "n", "c", "e", "l", "space", "r", "u", "n", "space")
        await pilot.press(*result.context.run.run_id, "enter")
        await pilot.pause()

        detail = app.query_one("#detail", Static)
        assert f"Run {result.context.run.run_id} is already completed." in str(detail.content)
