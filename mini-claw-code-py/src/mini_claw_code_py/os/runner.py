from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..types import Message
from .agent_registry import HostedAgentFactory, HostedAgentRegistry
from .bus import MessageBus
from .envelopes import EventEnvelope, MessageEnvelope
from .session_router import SessionRoute, SessionRouter
from .work import RunRecord, RunStore

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
        bus: MessageBus | None = None,
    ) -> None:
        self.registry = registry
        self.factory = factory
        self.router = router
        self.sessions = sessions
        self.runs = runs
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

        run = self.runs.start(
            task_id=_task_id_from_envelope(envelope),
            agent_name=definition.name,
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
        try:
            reply_text = await agent.execute(history, queue)
            session = self.sessions.save_runtime(
                session,
                messages=history,
                todos=agent.todo_board().items(),
                audit_entries=agent.audit_log().entries(),
                token_usage=agent.token_usage_tracker().turns(),
            )
            run = self.runs.finish(run.run_id, status="completed")
        except Exception:
            self.runs.finish(run.run_id, status="failed")
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
                    "status": "completed",
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


def _message_from_envelope(envelope: MessageEnvelope) -> Message:
    if envelope.kind == "system_message":
        return Message.system(envelope.content)
    return Message.user(envelope.content)


def _task_id_from_envelope(envelope: MessageEnvelope) -> str | None:
    task_id = envelope.metadata.get("task_id")
    if isinstance(task_id, str) and task_id.strip():
        return task_id.strip()
    return None
