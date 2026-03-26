from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Mapping

from .agent import AgentDone, AgentError, AgentEvent, AgentNotice, AgentTextDelta, AgentToolCall, tool_summary
from .context import (
    ContextCompactionSettings,
    compact_message_history,
    render_context_durability_prompt_section,
)
from .mcp import MCPRegistry, MCPToolAdapter
from .prompts import DEFAULT_PLAN_PROMPT_TEMPLATE, DEFAULT_SYSTEM_PROMPT_TEMPLATE, render_system_prompt
from .skills import SkillRegistry
from .streaming import StreamDone, StreamProvider, TextDelta
from .tools import AskTool, BashTool, EditTool, InputHandler, ReadTool, WriteTool
from .types import Message, StopReason, ToolDefinition, ToolSet


HARNESS_CORE_PROMPT_SECTION = """<harness_core_tools>
You are running inside a HarnessAgent with a bundled core tool profile.

Bundled core tools:
- `read`
- `write`
- `edit`
- `bash`
- `ask_user` when the runtime provides it

Default operating norms:
1. Read before editing when you need fresh context.
2. Prefer precise edits over broad rewrites when possible.
3. Use shell commands to inspect and verify work when they are the clearest tool.
4. Ask the user when required information is missing or ambiguous.
</harness_core_tools>"""


class HarnessAgent:
    def __init__(self, provider: StreamProvider) -> None:
        self.provider = provider
        self.tools = ToolSet()
        self._read_only = {"bash", "read", "ask_user"}
        self._mcp_registry: MCPRegistry | None = None
        self._core_tools_enabled = False
        self._ask_tool_enabled = False
        self._core_prompt_enabled = False
        self._context_durability_enabled = False
        self._context_prompt_enabled = False
        self._context_settings = ContextCompactionSettings()
        self.plan_system_prompt = DEFAULT_PLAN_PROMPT_TEMPLATE
        self.execution_system_prompt = DEFAULT_SYSTEM_PROMPT_TEMPLATE
        self.exit_plan_def = ToolDefinition.new(
            "exit_plan",
            "Signal that your plan is complete and ready for user review.",
        )

    def tool(self, tool: object) -> "HarnessAgent":
        self.tools.push(tool)  # type: ignore[arg-type]
        return self

    def read_only(self, names: list[str]) -> "HarnessAgent":
        self._read_only = set(names)
        return self

    def plan_prompt(self, prompt: str) -> "HarnessAgent":
        self.plan_system_prompt = prompt
        return self

    def system_prompt(self, prompt: str) -> "HarnessAgent":
        self.execution_system_prompt = prompt
        return self

    def enable_core_tools(
        self,
        handler: InputHandler | None = None,
    ) -> "HarnessAgent":
        if not self._core_tools_enabled:
            self.tool(ReadTool())
            self.tool(WriteTool())
            self.tool(EditTool())
            self.tool(BashTool())
            self._core_tools_enabled = True

        if handler is not None and not self._ask_tool_enabled:
            self.tool(AskTool(handler))
            self._ask_tool_enabled = True

        if not self._core_prompt_enabled:
            self.execution_system_prompt = _append_prompt_section(
                self.execution_system_prompt,
                HARNESS_CORE_PROMPT_SECTION,
            )
            self.plan_system_prompt = _append_prompt_section(
                self.plan_system_prompt,
                HARNESS_CORE_PROMPT_SECTION,
            )
            self._core_prompt_enabled = True

        return self

    def enable_default_skills(self, cwd: Path | None = None) -> "HarnessAgent":
        section = SkillRegistry.discover_default(cwd=Path.cwd() if cwd is None else cwd).prompt_section()
        if not section:
            return self

        target_cwd = Path.cwd() if cwd is None else cwd
        self.execution_system_prompt = render_system_prompt(
            self.execution_system_prompt,
            cwd=target_cwd,
            extra_sections=[section],
        )
        self.plan_system_prompt = render_system_prompt(
            self.plan_system_prompt,
            cwd=target_cwd,
            extra_sections=[section],
        )
        return self

    def enable_default_mcp(
        self,
        cwd: Path | None = None,
        home: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> "HarnessAgent":
        target_cwd = Path.cwd() if cwd is None else cwd
        registry = MCPRegistry.discover_default(cwd=target_cwd, home=home, env=env)
        self._mcp_registry = registry
        section = registry.prompt_section()
        if not section:
            return self

        self.execution_system_prompt = render_system_prompt(
            self.execution_system_prompt,
            cwd=target_cwd,
            extra_sections=[section],
        )
        self.plan_system_prompt = render_system_prompt(
            self.plan_system_prompt,
            cwd=target_cwd,
            extra_sections=[section],
        )
        return self

    def enable_context_durability(
        self,
        *,
        max_messages: int = 12,
        keep_recent: int = 6,
        max_estimated_tokens: int | None = 2400,
    ) -> "HarnessAgent":
        self._context_settings = ContextCompactionSettings(
            max_messages=max_messages,
            keep_recent=keep_recent,
            max_estimated_tokens=max_estimated_tokens,
        )
        self._context_durability_enabled = True

        if not self._context_prompt_enabled:
            section = render_context_durability_prompt_section()
            self.execution_system_prompt = _append_prompt_section(
                self.execution_system_prompt,
                section,
            )
            self.plan_system_prompt = _append_prompt_section(
                self.plan_system_prompt,
                section,
            )
            self._context_prompt_enabled = True

        return self

    async def plan(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        self._set_system_prompt(messages, self.plan_system_prompt)
        return await self._run_loop(messages, self._read_only, events)

    async def execute(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        self._set_system_prompt(messages, self.execution_system_prompt)
        return await self._run_loop(messages, None, events)

    async def _run_loop(
        self,
        messages: list[Message],
        allowed: set[str] | None,
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        async with AsyncExitStack() as stack:
            runtime_tools = self.tools.copy()
            mcp_summary: str | None = None
            if allowed is None and self._mcp_registry is not None and self._mcp_registry.all():
                adapter = await stack.enter_async_context(MCPToolAdapter(self._mcp_registry))
                mcp_summary = adapter.status_summary()
                for tool in adapter.tools():
                    runtime_tools.push(tool)

            all_defs = runtime_tools.definitions()
            defs = [definition for definition in all_defs if allowed is None or definition.name in allowed]
            if allowed is not None:
                defs.append(self.exit_plan_def)

            if mcp_summary:
                await events.put(AgentNotice(mcp_summary))

            while True:
                compaction = self._maybe_compact_messages(messages)
                if compaction is not None:
                    await events.put(AgentNotice(compaction.notice()))

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
                    tool = runtime_tools.get(call.name)
                    if tool is None:
                        content = f"error: unknown tool `{call.name}`"
                    else:
                        try:
                            content = await tool.call(call.arguments)
                        except Exception as exc:
                            content = f"error: {exc}"
                    results.append((call.id, content))

                messages.append(Message.assistant(turn))
                for call_id, content in results:
                    messages.append(Message.tool_result(call_id, content))

                if exit_plan:
                    text = turn.text or ""
                    await events.put(AgentDone(text))
                    return text

    @staticmethod
    def _set_system_prompt(messages: list[Message], prompt: str) -> None:
        system = Message.system(prompt)
        if messages and messages[0].kind == "system":
            messages[0] = system
        else:
            messages.insert(0, system)

    def _maybe_compact_messages(
        self,
        messages: list[Message],
    ):
        if not self._context_durability_enabled:
            return None
        return compact_message_history(messages, self._context_settings)


def render_harness_prompt_section() -> str:
    return HARNESS_CORE_PROMPT_SECTION


def _append_prompt_section(prompt: str, section: str) -> str:
    prompt_text = prompt.strip()
    section_text = section.strip()
    if not section_text:
        return prompt_text
    if section_text in prompt_text:
        return prompt_text
    if not prompt_text:
        return section_text
    return f"{prompt_text}\n\n{section_text}"
