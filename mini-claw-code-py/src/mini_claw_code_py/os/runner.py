from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..events import AgentContextCompaction, AgentDone, AgentError, AgentSubagentUpdate, AgentToolCall
from ..telemetry import resolve_pricing_profile
from ..types import Message
from .agent_registry import HostedAgentFactory, HostedAgentRegistry
from .bus import MessageBus
from .control import RunControlStore
from .envelopes import EventEnvelope, MessageEnvelope
from .session_router import SessionRoute, SessionRouter
from .work import (
    GoalStore,
    RunRecord,
    RunStore,
    SessionWorkStore,
    TaskStore,
    TeamRegistry,
    derive_work_title,
)

if TYPE_CHECKING:
    from ..harness import HarnessAgent
    from ..session import SessionRecord, SessionStore


@dataclass(slots=True)
class RunnerContext:
    envelope: MessageEnvelope
    route: SessionRoute
    session: "SessionRecord"
    run: RunRecord


@dataclass(slots=True)
class RunnerResult:
    context: RunnerContext
    agent: "HarnessAgent"
    history: list[Message]
    reply_text: str
    outbound: MessageEnvelope


class TurnRunner:
    def __init__(
        self,
        *,
        registry: HostedAgentRegistry,
        factory: HostedAgentFactory,
        router: SessionRouter,
        sessions: "SessionStore",
        runs: RunStore,
        teams: TeamRegistry | None = None,
        goals: GoalStore | None = None,
        tasks: TaskStore | None = None,
        session_work: SessionWorkStore | None = None,
        controls: RunControlStore | None = None,
        bus: MessageBus | None = None,
    ) -> None:
        self.registry = registry
        self.factory = factory
        self.router = router
        self.sessions = sessions
        self.runs = runs
        self.teams = teams
        self.goals = goals
        self.tasks = tasks
        self.session_work = session_work
        self.controls = controls or RunControlStore(runs.root)
        self.bus = bus

    async def run(
        self,
        envelope: MessageEnvelope,
        event_queue: "asyncio.Queue[object] | None" = None,
    ) -> RunnerResult:
        definition = self.registry.require(envelope.target_agent)
        route, session = self.router.resolve_or_create(
            target_agent=envelope.target_agent,
            thread_key=envelope.thread_key,
            cwd=definition.workspace_root,
        )
        agent = self.factory.build(definition)
        history = self.sessions.restore_into_agent(agent, session)
        history.append(_message_from_envelope(envelope))
        pricing = resolve_pricing_profile(self.factory.provider)
        turns_before = len(agent.token_usage_tracker().turns())
        prompt_before = agent.token_usage_tracker().total_prompt_tokens()
        completion_before = agent.token_usage_tracker().total_completion_tokens()
        task_id = _task_id_from_envelope(envelope)
        if task_id is None:
            task_id = self._resolve_or_create_session_task(
                session_id=session.id,
                agent_name=definition.name,
                content=envelope.content,
            )

        run = self.runs.start(
            task_id=task_id,
            agent_name=definition.name,
            source=envelope.source,
            thread_key=envelope.thread_key,
            session_id=session.id,
            trace_id=envelope.trace_id,
        )
        context = RunnerContext(
            envelope=envelope,
            route=route,
            session=session,
            run=run,
        )

        await self._publish_event(
            EventEnvelope(
                kind="run_started",
                trace_id=envelope.trace_id,
                payload={
                    "run_id": run.run_id,
                    "session_id": session.id,
                    "target_agent": definition.name,
                    "thread_key": envelope.thread_key,
                },
            )
        )

        queue = event_queue if event_queue is not None else asyncio.Queue()
        internal_queue: asyncio.Queue[object] = asyncio.Queue()
        observer = _RunObserver()
        relay = asyncio.create_task(_relay_events(internal_queue, queue, observer))
        try:
            reply_text = await agent.execute(
                history,
                internal_queue,
                should_cancel=lambda: self.controls.is_cancel_requested(run.run_id),
            )
            await relay
            turn_count = len(agent.token_usage_tracker().turns()) - turns_before
            prompt_tokens = agent.token_usage_tracker().total_prompt_tokens() - prompt_before
            completion_tokens = agent.token_usage_tracker().total_completion_tokens() - completion_before
            total_tokens = prompt_tokens + completion_tokens
            input_cost = pricing.input_cost(prompt_tokens)
            output_cost = pricing.output_cost(completion_tokens)
            total_cost = input_cost + output_cost
            context_pressure = agent.estimate_context_pressure_percent(history)
            final_status = "cancelled" if agent.last_exit_reason() == "cancelled" else "completed"
            session = self.sessions.save_runtime(
                session,
                messages=history,
                todos=agent.todo_board().items(),
                audit_entries=agent.audit_log().entries(),
                token_usage=agent.token_usage_tracker().turns(),
            )
            run = self.runs.finish(
                run.run_id,
                status=final_status,
                turn_count=turn_count,
                tool_call_count=observer.tool_call_count,
                subagent_count=observer.subagent_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_input_cost_usd=input_cost,
                estimated_output_cost_usd=output_cost,
                estimated_total_cost_usd=total_cost,
                context_pressure_percent=context_pressure,
                pricing_key=pricing.key,
                provider_name=pricing.provider_name,
                model_name=pricing.model_name,
            )
            if self.controls.is_cancel_requested(run.run_id):
                self.controls.resolve(
                    run.run_id,
                    result="cancelled" if final_status == "cancelled" else "completed",
                )
        except Exception:
            if not relay.done():
                relay.cancel()
            self.runs.finish(run.run_id, status="failed")
            if self.controls.is_cancel_requested(run.run_id):
                self.controls.resolve(run.run_id, result="rejected")
            await self._publish_event(
                EventEnvelope(
                    kind="run_finished",
                    trace_id=envelope.trace_id,
                    payload={
                        "run_id": run.run_id,
                        "session_id": session.id,
                        "target_agent": definition.name,
                        "status": "failed",
                    },
                )
            )
            raise

        outbound = MessageEnvelope(
            source=definition.name,
            target_agent=envelope.source,
            thread_key=envelope.thread_key,
            kind="system_message",
            content=reply_text,
            trace_id=envelope.trace_id,
            parent_run_id=run.run_id,
            metadata={
                "session_id": session.id,
                "target_agent": definition.name,
            },
        )

        await self._publish_outbound(outbound)
        await self._publish_event(
            EventEnvelope(
                kind="run_finished",
                trace_id=envelope.trace_id,
                payload={
                    "run_id": run.run_id,
                    "session_id": session.id,
                    "target_agent": definition.name,
                    "status": run.status,
                    "outbound_message_id": outbound.message_id,
                },
            )
        )

        return RunnerResult(
            context=RunnerContext(
                envelope=envelope,
                route=route,
                session=session,
                run=run,
            ),
            agent=agent,
            history=history,
            reply_text=reply_text,
            outbound=outbound,
        )

    async def _publish_outbound(self, envelope: MessageEnvelope) -> None:
        if self.bus is not None:
            await self.bus.publish_outbound(envelope)
            await self.bus.publish_event(
                EventEnvelope(
                    kind="outbound_message",
                    trace_id=envelope.trace_id,
                    payload={
                        "message_id": envelope.message_id,
                        "parent_run_id": envelope.parent_run_id,
                        "target_agent": envelope.target_agent,
                    },
                )
            )

    async def _publish_event(self, envelope: EventEnvelope) -> None:
        if self.bus is not None:
            await self.bus.publish_event(envelope)

    async def run_from_bus(
        self,
        event_queue: "asyncio.Queue[object] | None" = None,
    ) -> RunnerResult:
        if self.bus is None:
            raise ValueError("run_from_bus requires a MessageBus")
        envelope = await self.bus.consume_inbound()
        return await self.run(envelope, event_queue)

    def _resolve_or_create_session_task(
        self,
        *,
        session_id: str,
        agent_name: str,
        content: str,
    ) -> str | None:
        if self.goals is None or self.tasks is None or self.session_work is None or self.teams is None:
            return None
        existing = self.session_work.get(session_id)
        if existing is not None:
            return existing.task_id
        title = derive_work_title(content)
        team = self.teams.team_for_agent(agent_name)
        goal = self.goals.create(
            title=title,
            description=content.strip(),
            primary_team=team.name,
        )
        self.goals.update_status(goal.goal_id, "in_progress")
        task = self.tasks.assign(
            goal_id=goal.goal_id,
            team_id=team.name,
            agent_name=agent_name,
            title=title,
        )
        self.tasks.update_status(task.task_id, "in_progress")
        self.session_work.bind(
            session_id=session_id,
            goal_id=goal.goal_id,
            task_id=task.task_id,
            team_id=team.name,
        )
        return task.task_id


def _message_from_envelope(envelope: MessageEnvelope) -> Message:
    if envelope.kind == "system_message":
        return Message.system(envelope.content)
    return Message.user(envelope.content)


def _task_id_from_envelope(envelope: MessageEnvelope) -> str | None:
    task_id = envelope.metadata.get("task_id")
    if isinstance(task_id, str) and task_id.strip():
        return task_id.strip()
    return None


class _RunObserver:
    def __init__(self) -> None:
        self.tool_call_count = 0
        self.subagent_count = 0
        self.compactions = 0

    def observe(self, event: object) -> None:
        if isinstance(event, AgentToolCall):
            self.tool_call_count += 1
        elif isinstance(event, AgentSubagentUpdate) and event.status == "started":
            self.subagent_count += 1
        elif isinstance(event, AgentContextCompaction):
            self.compactions += 1


async def _relay_events(
    source: "asyncio.Queue[object]",
    target: "asyncio.Queue[object]",
    observer: _RunObserver,
) -> None:
    while True:
        event = await source.get()
        observer.observe(event)
        await target.put(event)
        if isinstance(event, AgentDone | AgentError):
            return
