from __future__ import annotations

import asyncio

from .agent import AgentDone, AgentError, AgentEvent, AgentTextDelta, AgentToolCall, tool_summary
from .prompts import DEFAULT_PLAN_PROMPT_TEMPLATE
from .streaming import StreamDone, StreamProvider, TextDelta
from .types import Message, StopReason, ToolDefinition, ToolSet


class PlanAgent:
    def __init__(self, provider: StreamProvider) -> None:
        self.provider = provider
        self.tools = ToolSet()
        self._read_only = {"bash", "read", "ask_user"}
        self.plan_system_prompt = DEFAULT_PLAN_PROMPT_TEMPLATE
        self.exit_plan_def = ToolDefinition.new(
            "exit_plan",
            "Signal that your plan is complete and ready for user review.",
        )

    def tool(self, tool: object) -> "PlanAgent":
        self.tools.push(tool)  # type: ignore[arg-type]
        return self

    def read_only(self, names: list[str]) -> "PlanAgent":
        self._read_only = set(names)
        return self

    def plan_prompt(self, prompt: str) -> "PlanAgent":
        self.plan_system_prompt = prompt
        return self

    async def plan(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        if not messages or messages[0].kind != "system":
            messages.insert(0, Message.system(self.plan_system_prompt))
        return await self._run_loop(messages, self._read_only, events)

    async def execute(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        return await self._run_loop(messages, None, events)

    async def _run_loop(
        self,
        messages: list[Message],
        allowed: set[str] | None,
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        all_defs = self.tools.definitions()
        defs = [definition for definition in all_defs if allowed is None or definition.name in allowed]
        if allowed is not None:
            defs.append(self.exit_plan_def)

        while True:
            stream_queue: asyncio.Queue[object] = asyncio.Queue()

            async def forward() -> None:
                while True:
                    event = await stream_queue.get()
                    if isinstance(event, TextDelta):
                        await events.put(AgentTextDelta(event.text))
                    if isinstance(event, StreamDone):
                        return

            forwarder = asyncio.create_task(forward())

            try:
                turn = await self.provider.stream_chat(messages, defs, stream_queue)  # type: ignore[arg-type]
            except Exception as exc:
                await events.put(AgentError(str(exc)))
                forwarder.cancel()
                raise

            await forwarder

            if turn.stop_reason is StopReason.STOP:
                text = turn.text or ""
                await events.put(AgentDone(text))
                messages.append(Message.assistant(turn))
                return text

            results: list[tuple[str, str]] = []
            exit_plan = False

            for call in turn.tool_calls:
                if allowed is not None and call.name == "exit_plan":
                    results.append((call.id, "Plan submitted for review."))
                    exit_plan = True
                    continue

                if allowed is not None and call.name not in allowed:
                    results.append(
                        (
                            call.id,
                            f"error: tool '{call.name}' is not available in planning mode",
                        )
                    )
                    continue

                await events.put(AgentToolCall(call.name, tool_summary(call)))
                tool = self.tools.get(call.name)
                if tool is None:
                    content = f"error: unknown tool `{call.name}`"
                else:
                    try:
                        content = await tool.call(call.arguments)
                    except Exception as exc:
                        content = f"error: {exc}"
                results.append((call.id, content))

            plan_text = turn.text or ""
            messages.append(Message.assistant(turn))
            for call_id, content in results:
                messages.append(Message.tool_result(call_id, content))

            if exit_plan:
                await events.put(AgentDone(plan_text))
                return plan_text
