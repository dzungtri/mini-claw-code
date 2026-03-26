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
from .memory import (
    MemoryRegistry,
    MemoryUpdateQueue,
    MemoryUpdater,
    latest_memory_exchange,
    should_consider_memory_update,
)
from .mcp import MCPRegistry, MCPToolAdapter
from .prompts import DEFAULT_PLAN_PROMPT_TEMPLATE, DEFAULT_SYSTEM_PROMPT_TEMPLATE, render_system_prompt
from .skills import SkillRegistry
from .streaming import StreamDone, StreamProvider, TextDelta
from .tools import AskTool, BashTool, EditTool, InputHandler, ReadTool, WriteTool
from .types import Message, Provider, StopReason, ToolDefinition, ToolSet
from .workspace import (
    WorkspaceBashTool,
    WorkspaceConfig,
    WorkspaceEditTool,
    WorkspaceReadTool,
    WorkspaceWriteTool,
    render_workspace_prompt_section,
)


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
        self._memory_registry = MemoryRegistry()
        self._memory_update_queue: MemoryUpdateQueue | None = None
        self._memory_update_scope = "user"
        self._background_notice_queue: "asyncio.Queue[AgentNotice]" = asyncio.Queue()
        self._workspace_config: WorkspaceConfig | None = None
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
            self._install_core_tools()
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

    def workspace(
        self,
        root: str | Path,
    ) -> "HarnessAgent":
        existing = self._workspace_config
        self._workspace_config = WorkspaceConfig(
            root=Path(root),
            scratch=existing.scratch if existing is not None else None,
            outputs=existing.outputs if existing is not None else None,
            uploads=existing.uploads if existing is not None else None,
            allow_destructive_bash=existing.allow_destructive_bash if existing is not None else False,
        )
        self._refresh_workspace_tools()
        return self

    def scratch_dir(
        self,
        path: str | Path,
    ) -> "HarnessAgent":
        config = self._require_or_default_workspace()
        self._workspace_config = WorkspaceConfig(
            root=config.root,
            scratch=Path(path),
            outputs=config.outputs,
            uploads=config.uploads,
            allow_destructive_bash=config.allow_destructive_bash,
        )
        self._refresh_workspace_tools()
        return self

    def outputs_dir(
        self,
        path: str | Path,
    ) -> "HarnessAgent":
        config = self._require_or_default_workspace()
        self._workspace_config = WorkspaceConfig(
            root=config.root,
            scratch=config.scratch,
            outputs=Path(path),
            uploads=config.uploads,
            allow_destructive_bash=config.allow_destructive_bash,
        )
        self._refresh_workspace_tools()
        return self

    def uploads_dir(
        self,
        path: str | Path,
    ) -> "HarnessAgent":
        config = self._require_or_default_workspace()
        self._workspace_config = WorkspaceConfig(
            root=config.root,
            scratch=config.scratch,
            outputs=config.outputs,
            uploads=Path(path),
            allow_destructive_bash=config.allow_destructive_bash,
        )
        self._refresh_workspace_tools()
        return self

    def enable_workspace(
        self,
        root: str | Path,
        *,
        scratch: str | Path | None = None,
        outputs: str | Path | None = None,
        uploads: str | Path | None = None,
        allow_destructive_bash: bool = False,
    ) -> "HarnessAgent":
        self._workspace_config = WorkspaceConfig(
            root=Path(root),
            scratch=Path(scratch) if scratch is not None else None,
            outputs=Path(outputs) if outputs is not None else None,
            uploads=Path(uploads) if uploads is not None else None,
            allow_destructive_bash=allow_destructive_bash,
        )
        self._refresh_workspace_tools()
        return self

    def allow_destructive_bash(
        self,
        enabled: bool = True,
    ) -> "HarnessAgent":
        config = self._require_or_default_workspace()
        self._workspace_config = WorkspaceConfig(
            root=config.root,
            scratch=config.scratch,
            outputs=config.outputs,
            uploads=config.uploads,
            allow_destructive_bash=enabled,
        )
        self._refresh_workspace_tools()
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

    def enable_memory_file(
        self,
        path: str | Path,
    ) -> "HarnessAgent":
        self._memory_registry.add("project", path)
        return self

    def enable_project_memory_file(
        self,
        path: str | Path,
    ) -> "HarnessAgent":
        self._memory_registry.add("project", path)
        return self

    def enable_user_memory_file(
        self,
        path: str | Path,
    ) -> "HarnessAgent":
        self._memory_registry.add("user", path)
        return self

    def enable_default_memory(
        self,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "HarnessAgent":
        self._memory_registry.extend(
            MemoryRegistry.discover_default(cwd=cwd, home=home).all()
        )
        return self

    def enable_memory_updates(
        self,
        provider: Provider | None = None,
        *,
        debounce_seconds: float = 2.0,
        target_scope: str = "user",
        max_messages: int = 6,
    ) -> "HarnessAgent":
        chat_provider = provider or self._default_memory_update_provider()
        if chat_provider is None:
            raise ValueError(
                "Memory updates require a Provider with a chat() method. "
                "Pass provider=... explicitly when the main stream provider does not support chat()."
            )
        self._memory_update_queue = MemoryUpdateQueue(
            MemoryUpdater(chat_provider, max_messages=max_messages),
            debounce_seconds=debounce_seconds,
            on_notice=self._emit_background_notice,
        )
        self._memory_update_scope = target_scope
        return self

    def notice_queue(self) -> "asyncio.Queue[AgentNotice]":
        return self._background_notice_queue

    async def flush_memory_updates(self) -> None:
        if self._memory_update_queue is None:
            return
        await self._memory_update_queue.flush()

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
        self._set_system_prompt(messages, self._effective_prompt(self.plan_system_prompt))
        return await self._run_loop(messages, self._read_only, events)

    async def execute(
        self,
        messages: list[Message],
        events: "asyncio.Queue[AgentEvent]",
    ) -> str:
        self._set_system_prompt(messages, self._effective_prompt(self.execution_system_prompt))
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

            memory_summary = self._memory_registry.status_summary()
            if memory_summary:
                await events.put(AgentNotice(memory_summary))

            workspace_summary = self._workspace_config.status_summary() if self._workspace_config is not None else None
            if workspace_summary:
                await events.put(AgentNotice(workspace_summary))

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
                    text = (turn.text or "").strip()
                    if not text:
                        text = "I don't have a textual reply for that turn. Please try again."
                    messages.append(Message.assistant(turn))
                    notice = await self._queue_memory_update(messages)
                    if notice:
                        await events.put(AgentNotice(notice))
                    await events.put(AgentDone(text))
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
                    notice = await self._queue_memory_update(messages)
                    if notice:
                        await events.put(AgentNotice(notice))
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

    def _effective_prompt(self, prompt: str) -> str:
        effective = prompt
        memory_section = self._memory_registry.prompt_section()
        if memory_section:
            effective = _append_prompt_section(effective, memory_section)
        if self._workspace_config is not None:
            effective = _append_prompt_section(
                effective,
                render_workspace_prompt_section(self._workspace_config),
            )
        return effective

    def _default_memory_update_provider(self) -> Provider | None:
        provider = self.provider
        chat = getattr(provider, "chat", None)
        if callable(chat):
            return provider  # type: ignore[return-value]
        return None

    async def _queue_memory_update(self, messages: list[Message]) -> str | None:
        if self._memory_update_queue is None:
            return None
        source = self._memory_registry.get(self._memory_update_scope)
        if source is None:
            return None
        snapshot = latest_memory_exchange(messages)
        if not should_consider_memory_update(snapshot):
            return None
        await self._memory_update_queue.add(source, snapshot)
        return f"Memory update queued for {source.scope} memory."

    async def _emit_background_notice(self, message: str) -> None:
        await self._background_notice_queue.put(AgentNotice(message))

    def _require_or_default_workspace(self) -> WorkspaceConfig:
        if self._workspace_config is not None:
            return self._workspace_config
        return WorkspaceConfig(root=Path.cwd())

    def _refresh_workspace_tools(self) -> None:
        if not self._core_tools_enabled:
            return
        self._install_core_tools()

    def _install_core_tools(self) -> None:
        if self._workspace_config is None:
            self.tool(ReadTool())
            self.tool(WriteTool())
            self.tool(EditTool())
            self.tool(BashTool())
            return
        self.tool(WorkspaceReadTool(self._workspace_config))
        self.tool(WorkspaceWriteTool(self._workspace_config))
        self.tool(WorkspaceEditTool(self._workspace_config))
        self.tool(WorkspaceBashTool(self._workspace_config))


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
