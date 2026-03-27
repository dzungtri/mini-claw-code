from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Mapping

from .control_plane import (
    AuditEntry,
    AuditLog,
    ControlPlaneSettings,
    approval_message_for_tool,
    classify_loop,
    control_plane_profile,
    is_mutating_tool,
    is_verification_tool,
    render_control_plane_prompt_section,
    tool_call_signature,
)
from .context import (
    ARCHIVED_CONTEXT_OPEN,
    ContextCompactionSettings,
    compact_message_history,
    render_context_durability_prompt_section,
)
from .events import (
    AgentApprovalUpdate,
    AgentContextCompaction,
    AgentDone,
    AgentError,
    AgentEvent,
    AgentMemoryUpdate,
    AgentNotice,
    AgentSubagentUpdate,
    AgentTextDelta,
    AgentTokenUsage,
    AgentTodoUpdate,
    AgentToolCall,
    tool_summary,
)
from .memory import (
    MemoryRegistry,
    MemoryNotice,
    MemoryUpdateQueue,
    MemoryUpdater,
    latest_memory_exchange,
    should_consider_memory_update,
)
from .mcp import MCPRegistry, MCPToolAdapter
from .prompts import DEFAULT_PLAN_PROMPT_TEMPLATE, DEFAULT_SYSTEM_PROMPT_TEMPLATE, render_system_prompt
from .skills import SkillRegistry
from .streaming import StreamDone, StreamProvider, TextDelta
from .subagent import SubagentTool, render_harness_subagent_prompt_section
from .tool_universe import (
    DeferredToolRegistry,
    ToolSearchTool,
    render_tool_universe_prompt_section,
    tool_universe_status_summary,
)
from .todos import TodoBoard, TodoItem, WriteTodosTool, render_todo_prompt_section
from .telemetry import (
    TokenUsageSnapshot,
    TokenUsageTracker,
    estimate_assistant_turn_tokens,
    estimate_messages_tokens,
    estimate_tool_definitions_tokens,
)
from .tools import AskTool, BashTool, EditTool, InputHandler, ReadTool, WriteTool
from .types import AssistantTurn, Message, Provider, StopReason, ToolDefinition, ToolSet
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
- `write_todos`
- `ask_user` when the runtime provides it

Default operating norms:
1. Read before editing when you need fresh context.
2. Prefer precise edits over broad rewrites when possible.
3. Use shell commands to inspect and verify work when they are the clearest tool.
4. Use `write_todos` to maintain a short visible task list for non-trivial work.
5. Ask the user when required information is missing or ambiguous.
</harness_core_tools>"""


class HarnessAgent:
    def __init__(self, provider: StreamProvider) -> None:
        self.provider = provider
        self.tools = ToolSet()
        self._read_only = {"bash", "read", "ask_user", "write_todos"}
        self._memory_registry = MemoryRegistry()
        self._memory_update_queue: MemoryUpdateQueue | None = None
        self._memory_update_scope = "user"
        self._background_notice_queue: "asyncio.Queue[object]" = asyncio.Queue()
        self._audit_log = AuditLog()
        self._workspace_config: WorkspaceConfig | None = None
        self._mcp_registry: MCPRegistry | None = None
        self._skill_registry: SkillRegistry | None = None
        self._todo_board = TodoBoard()
        self._core_tools_enabled = False
        self._ask_tool_enabled = False
        self._core_prompt_enabled = False
        self._subagent_enabled = False
        self._subagent_prompt_enabled = False
        self._subagent_provider: Provider | None = None
        self._subagent_tool_names: tuple[str, ...] = ()
        self._subagent_max_turns = 8
        self._max_parallel_subagents = 2
        self._context_durability_enabled = False
        self._context_prompt_enabled = False
        self._context_settings = ContextCompactionSettings()
        self._tool_universe_enabled = False
        self._tool_universe_prompt_enabled = False
        self._control_plane_enabled = False
        self._control_plane_prompt_enabled = False
        self._control_settings = ControlPlaneSettings()
        self._control_profile_name = "balanced"
        self._token_usage_enabled = False
        self._token_usage_tracker = TokenUsageTracker()
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
            todo_section = render_todo_prompt_section()
            self.execution_system_prompt = _append_prompt_section(
                self.execution_system_prompt,
                todo_section,
            )
            self.plan_system_prompt = _append_prompt_section(
                self.plan_system_prompt,
                todo_section,
            )
            self._core_prompt_enabled = True

        return self

    def todo_board(self) -> TodoBoard:
        return self._todo_board

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
        registry = SkillRegistry.discover_default(cwd=Path.cwd() if cwd is None else cwd)
        self._skill_registry = registry
        section = registry.prompt_section()
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

    def enable_tool_universe_management(self) -> "HarnessAgent":
        self._tool_universe_enabled = True
        if not self._tool_universe_prompt_enabled:
            section = render_tool_universe_prompt_section()
            self.execution_system_prompt = _append_prompt_section(
                self.execution_system_prompt,
                section,
            )
            self._tool_universe_prompt_enabled = True
        return self

    def enable_subagents(
        self,
        provider: Provider | None = None,
        *,
        tool_names: list[str] | None = None,
        max_turns: int = 8,
        max_parallel_subagents: int = 2,
        system_prompt: str | None = None,
    ) -> "HarnessAgent":
        chat_provider = provider or self._default_chat_provider()
        if chat_provider is None:
            raise ValueError(
                "Subagents require a Provider with a chat() method. "
                "Pass provider=... explicitly when the main stream provider does not support chat()."
            )
        if max_parallel_subagents < 1:
            raise ValueError("max_parallel_subagents must be at least 1")

        self._subagent_provider = chat_provider
        self._subagent_tool_names = tuple(tool_names or self._default_subagent_tool_names())
        self._subagent_max_turns = max_turns
        self._max_parallel_subagents = max_parallel_subagents

        tool = SubagentTool(
            chat_provider,
            self._subagent_tools_factory,
        ).max_turns(max_turns)
        if system_prompt is not None:
            tool.system_prompt(system_prompt)
        self.tool(tool)
        self._subagent_enabled = True

        if not self._subagent_prompt_enabled:
            section = render_harness_subagent_prompt_section(self._max_parallel_subagents)
            self.execution_system_prompt = _append_prompt_section(
                self.execution_system_prompt,
                section,
            )
            self._subagent_prompt_enabled = True
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

    def notice_queue(self) -> "asyncio.Queue[object]":
        return self._background_notice_queue

    def audit_log(self) -> AuditLog:
        return self._audit_log

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

    def enable_control_plane(
        self,
        *,
        profile: str = "balanced",
        warn_repeated_tool_calls: int | None = None,
        block_repeated_tool_calls: int | None = None,
        require_overwrite_approval: bool | None = None,
        require_risky_bash_approval: bool | None = None,
        warn_on_missing_verification: bool | None = None,
    ) -> "HarnessAgent":
        settings = control_plane_profile(profile)
        self._control_profile_name = profile
        self._control_settings = ControlPlaneSettings(
            warn_repeated_tool_calls=(
                settings.warn_repeated_tool_calls
                if warn_repeated_tool_calls is None
                else warn_repeated_tool_calls
            ),
            block_repeated_tool_calls=(
                settings.block_repeated_tool_calls
                if block_repeated_tool_calls is None
                else block_repeated_tool_calls
            ),
            require_overwrite_approval=(
                settings.require_overwrite_approval
                if require_overwrite_approval is None
                else require_overwrite_approval
            ),
            require_risky_bash_approval=(
                settings.require_risky_bash_approval
                if require_risky_bash_approval is None
                else require_risky_bash_approval
            ),
            warn_on_missing_verification=(
                settings.warn_on_missing_verification
                if warn_on_missing_verification is None
                else warn_on_missing_verification
            ),
            audit_limit=self._control_settings.audit_limit,
        )
        self._audit_log = AuditLog(limit=self._control_settings.audit_limit)
        self._control_plane_enabled = True

        if not self._control_plane_prompt_enabled:
            section = render_control_plane_prompt_section()
            self.execution_system_prompt = _append_prompt_section(
                self.execution_system_prompt,
                section,
            )
            self.plan_system_prompt = _append_prompt_section(
                self.plan_system_prompt,
                section,
            )
            self._control_plane_prompt_enabled = True

        return self

    def control_plane_profile_name(self) -> str | None:
        if not self._control_plane_enabled:
            return None
        return self._control_profile_name

    def enable_token_usage_tracing(self) -> "HarnessAgent":
        self._token_usage_enabled = True
        return self

    def token_usage_tracker(self) -> TokenUsageTracker:
        return self._token_usage_tracker

    def restore_runtime_state(
        self,
        *,
        todos: list[TodoItem | dict[str, str] | str] | None = None,
        audit_entries: list[AuditEntry | dict[str, str]] | None = None,
        token_usage: list[TokenUsageSnapshot | dict[str, int]] | None = None,
    ) -> "HarnessAgent":
        self._todo_board.replace([] if todos is None else list(todos))
        self._audit_log.replace([] if audit_entries is None else list(audit_entries))
        self._token_usage_tracker.replace([] if token_usage is None else list(token_usage))
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
            deferred_registry = DeferredToolRegistry()
            mcp_summary: str | None = None
            if allowed is None and self._mcp_registry is not None and self._mcp_registry.all():
                adapter = await stack.enter_async_context(MCPToolAdapter(self._mcp_registry))
                mcp_summary = adapter.status_summary()
                if self._tool_universe_enabled:
                    for tool in adapter.tools():
                        deferred_registry.register(tool, source="mcp")
                    runtime_tools.push(ToolSearchTool(deferred_registry, runtime_tools))
                else:
                    for tool in adapter.tools():
                        runtime_tools.push(tool)

            built_in_count = len(self.tools.definitions())
            deferred_count = deferred_registry.count()
            skill_count = len(self._skill_registry.all()) if self._skill_registry is not None else 0

            memory_summary = self._memory_registry.status_summary()
            if memory_summary:
                await events.put(AgentNotice(memory_summary))

            workspace_summary = self._workspace_config.status_summary() if self._workspace_config is not None else None
            if workspace_summary:
                await events.put(AgentNotice(workspace_summary))

            if self._subagent_enabled:
                await events.put(
                    AgentNotice(
                        "Subagent capability available: "
                        f"tools={list(self._subagent_tool_names)}, "
                        f"max_parallel={self._max_parallel_subagents}, "
                        f"max_turns={self._subagent_max_turns}"
                    )
                )

            if mcp_summary:
                await events.put(AgentNotice(mcp_summary))

            if allowed is None and self._tool_universe_enabled:
                await events.put(
                    AgentNotice(
                        tool_universe_status_summary(
                            built_in_count=built_in_count,
                            skill_count=skill_count,
                            deferred_count=deferred_count,
                        )
                    )
                )

            if allowed is None and self._control_plane_enabled:
                await events.put(
                    AgentNotice(
                        "Control plane active: "
                        f"profile={self._control_profile_name}, "
                        "clarification rules, approval gates, verification warnings, loop detection, audit log."
                    )
                )

            if allowed is not None:
                allowed_tools = ", ".join(
                    sorted(definition.name for definition in runtime_tools.definitions() if definition.name in allowed)
                )
                allowed_tools = f"{allowed_tools}, exit_plan" if allowed_tools else "exit_plan"
                await events.put(
                    AgentNotice(
                        "Planning mode active: external writes and subagents are blocked. "
                        f"Allowed tools: {allowed_tools}."
                    )
                )

            recent_tool_signatures: list[str] = []

            while True:
                all_defs = runtime_tools.definitions()
                defs = [definition for definition in all_defs if allowed is None or definition.name in allowed]
                if allowed is not None:
                    defs.append(self.exit_plan_def)

                compaction = self._maybe_compact_messages(messages)
                if compaction is not None:
                    await events.put(
                        AgentContextCompaction(
                            message=compaction.notice(),
                            archived_messages=compaction.archived_messages,
                            kept_messages=compaction.kept_messages,
                            triggered_by=compaction.triggered_by,
                        )
                    )
                    await events.put(AgentNotice(compaction.notice()))

                prompt_token_estimate = self._estimate_prompt_tokens(messages, defs)
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

                self._record_token_usage(turn, prompt_token_estimate, events)

                if turn.stop_reason is StopReason.STOP:
                    text = (turn.text or "").strip()
                    if not text:
                        text = "I don't have a textual reply for that turn. Please try again."
                    messages.append(Message.assistant(turn))
                    if (
                        allowed is None
                        and self._control_plane_enabled
                        and self._mutation_since_last_verification(messages)
                        and self._control_settings.warn_on_missing_verification
                    ):
                        warning = "Control plane warning: final answer was produced without a clear verification step after mutation."
                        self._audit_log.push("verify", warning)
                        await events.put(AgentNotice(warning))
                    if allowed is None and self._todo_board.complete_all():
                        await events.put(self._todo_event())
                        await events.put(AgentNotice(self._todo_board.notice()))
                    notice = await self._queue_memory_update(messages)
                    if notice:
                        await events.put(notice)
                        await events.put(AgentNotice(notice.message))
                    await events.put(AgentDone(text))
                    return text

                results: list[tuple[str, str]] = []
                exit_plan = False

                subagent_calls_seen = 0
                subagent_tasks: list[asyncio.Task[str]] = []
                subagent_positions: list[tuple[str, int]] = []
                subagent_briefs: list[str] = []

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
                    if call.name == "ask_user" and self._control_plane_enabled:
                        self._audit_log.push("clarify", f"Asked user: {_tool_detail(call.arguments)}")

                    tool = runtime_tools.get(call.name)
                    if tool is None:
                        content = f"error: unknown tool `{call.name}`"
                    elif (
                        allowed is None
                        and self._control_plane_enabled
                        and self._should_block_loop(call.name, call.arguments, recent_tool_signatures, events)
                    ):
                        content = "error: control plane blocked a repeated tool-call loop"
                    elif (
                        allowed is None
                        and self._control_plane_enabled
                        and await self._requires_approval(call.name, call.arguments, runtime_tools, events)
                    ):
                        content = "error: user denied approval"
                    elif call.name == "subagent" and allowed is None:
                        subagent_calls_seen += 1
                        if subagent_calls_seen > self._max_parallel_subagents:
                            content = (
                                "error: too many subagent calls in one turn "
                                f"(limit: {self._max_parallel_subagents})"
                            )
                        else:
                            brief = _tool_detail(call.arguments)
                            await events.put(
                                AgentSubagentUpdate(
                                    message=f"Subagent started ({subagent_calls_seen}/{self._max_parallel_subagents}): {brief}",
                                    status="started",
                                    index=subagent_calls_seen,
                                    total=self._max_parallel_subagents,
                                    brief=brief,
                                )
                            )
                            await events.put(
                                AgentNotice(
                                    f"Subagent started ({subagent_calls_seen}/{self._max_parallel_subagents}): {brief}"
                                )
                            )
                            subagent_tasks.append(
                                asyncio.create_task(self._run_subagent_call(tool, call.arguments))
                            )
                            subagent_positions.append((call.id, len(results)))
                            subagent_briefs.append(brief)
                            results.append((call.id, ""))
                            continue
                    else:
                        try:
                            content = await tool.call(call.arguments)
                        except Exception as exc:
                            content = f"error: {exc}"
                    results.append((call.id, content))
                    if self._control_plane_enabled:
                        recent_tool_signatures.append(tool_call_signature(call.name, call.arguments))
                        recent_tool_signatures[:] = recent_tool_signatures[-20:]
                    if call.name == "write_todos" and not content.startswith("error:"):
                        await events.put(self._todo_event())
                        await events.put(AgentNotice(self._todo_board.notice()))
                    if self._control_plane_enabled and not content.startswith("error:"):
                        self._record_control_plane_success(call.name, call.arguments)

                if subagent_tasks:
                    subagent_outputs = await asyncio.gather(*subagent_tasks)
                    for index, ((call_id, result_index), content) in enumerate(
                        zip(subagent_positions, subagent_outputs, strict=False),
                        start=1,
                    ):
                        results[result_index] = (call_id, content)
                        brief = subagent_briefs[index - 1]
                        await events.put(
                            AgentSubagentUpdate(
                                message=f"Subagent finished ({index}/{len(subagent_outputs)}): {brief}",
                                status="finished",
                                index=index,
                                total=len(subagent_outputs),
                                brief=brief,
                            )
                        )
                        await events.put(
                            AgentNotice(
                                f"Subagent finished ({index}/{len(subagent_outputs)}): {brief}"
                            )
                        )

                if subagent_calls_seen > self._max_parallel_subagents:
                    await events.put(
                        AgentNotice(
                            "Subagent limit applied: "
                            f"kept first {self._max_parallel_subagents} call(s) in this turn."
                        )
                    )

                messages.append(Message.assistant(turn))
                for call_id, content in results:
                    messages.append(Message.tool_result(call_id, content))

                if exit_plan:
                    text = turn.text or ""
                    notice = await self._queue_memory_update(messages)
                    if notice:
                        await events.put(notice)
                        await events.put(AgentNotice(notice.message))
                    await events.put(AgentDone(text))
                    return text

    @staticmethod
    def _set_system_prompt(messages: list[Message], prompt: str) -> None:
        system = Message.system(prompt)
        if (
            messages
            and messages[0].kind == "system"
            and isinstance(messages[0].content, str)
            and not messages[0].content.strip().startswith(ARCHIVED_CONTEXT_OPEN)
        ):
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

    def _estimate_prompt_tokens(
        self,
        messages: list[Message],
        defs: list[ToolDefinition],
    ) -> int:
        return estimate_messages_tokens(messages) + estimate_tool_definitions_tokens(defs)

    def _record_token_usage(
        self,
        turn: AssistantTurn,
        prompt_token_estimate: int,
        events: "asyncio.Queue[AgentEvent]",
    ) -> None:
        if not self._token_usage_enabled:
            return
        snapshot = self._token_usage_tracker.record(
            prompt_tokens=prompt_token_estimate,
            completion_tokens=estimate_assistant_turn_tokens(turn),
        )
        events.put_nowait(AgentTokenUsage(snapshot.notice(self._token_usage_tracker.total_tokens())))

    def _default_memory_update_provider(self) -> Provider | None:
        provider = self.provider
        chat = getattr(provider, "chat", None)
        if callable(chat):
            return provider  # type: ignore[return-value]
        return None

    def _default_chat_provider(self) -> Provider | None:
        provider = self.provider
        chat = getattr(provider, "chat", None)
        if callable(chat):
            return provider  # type: ignore[return-value]
        return None

    async def _queue_memory_update(self, messages: list[Message]) -> AgentMemoryUpdate | None:
        if self._memory_update_queue is None:
            return None
        source = self._memory_registry.get(self._memory_update_scope)
        if source is None:
            return None
        snapshot = latest_memory_exchange(messages)
        if not should_consider_memory_update(snapshot):
            return None
        await self._memory_update_queue.add(source, snapshot)
        return AgentMemoryUpdate(
            message=f"Memory update queued for {source.scope} memory.",
            status="queued",
            scope=source.scope,
        )

    async def _emit_background_notice(self, notice: MemoryNotice) -> None:
        event = AgentMemoryUpdate(
            message=notice.message,
            status=notice.status,
            scope=notice.scope,
        )
        await self._background_notice_queue.put(event)
        await self._background_notice_queue.put(AgentNotice(notice.message))

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
            self.tool(WriteTodosTool(self._todo_board))
            return
        self.tool(WorkspaceReadTool(self._workspace_config))
        self.tool(WorkspaceWriteTool(self._workspace_config))
        self.tool(WorkspaceEditTool(self._workspace_config))
        self.tool(WorkspaceBashTool(self._workspace_config))
        self.tool(WriteTodosTool(self._todo_board))

    def _default_subagent_tool_names(self) -> list[str]:
        candidates = ["read", "write", "edit", "bash"]
        return [name for name in candidates if self.tools.get(name) is not None]

    def _subagent_tools_factory(self) -> ToolSet:
        tools = ToolSet()
        for name in self._subagent_tool_names:
            tool = self.tools.get(name)
            if tool is None or name == "subagent":
                continue
            tools.push(tool)
        return tools

    @staticmethod
    async def _run_subagent_call(tool: object, args: object) -> str:
        try:
            return await tool.call(args)  # type: ignore[call-arg]
        except Exception as exc:
            return f"error: {exc}"

    async def _requires_approval(
        self,
        name: str,
        args: object,
        runtime_tools: ToolSet,
        events: "asyncio.Queue[AgentEvent]",
    ) -> bool:
        message = approval_message_for_tool(name, args, self._control_settings)
        if message is None:
            return False

        self._audit_log.push("approval", f"Approval required for {name}: {message}")
        await events.put(
            AgentApprovalUpdate(
                message=f"Approval required: {message}",
                status="required",
                tool_name=name,
            )
        )
        await events.put(AgentNotice(f"Approval required: {message}"))
        ask_tool = runtime_tools.get("ask_user")
        if ask_tool is None:
            return True

        answer = await ask_tool.call(
            {
                "question": message,
                "options": ["Approve", "Cancel"],
            }
        )
        normalized = answer.strip().lower()
        approved = normalized in {"approve", "approved", "yes", "y", "1"}
        if approved:
            self._audit_log.push("approval", f"Approval granted for {name}")
            await events.put(
                AgentApprovalUpdate(
                    message=f"Approval granted: {message}",
                    status="granted",
                    tool_name=name,
                )
            )
            await events.put(AgentNotice(f"Approval granted: {message}"))
            return False

        self._audit_log.push("approval", f"Approval denied for {name}")
        await events.put(
            AgentApprovalUpdate(
                message=f"Approval denied: {message}",
                status="denied",
                tool_name=name,
            )
        )
        await events.put(AgentNotice(f"Approval denied: {message}"))
        return True

    def _should_block_loop(
        self,
        name: str,
        args: object,
        recent_tool_signatures: list[str],
        events: "asyncio.Queue[AgentEvent]",
    ) -> bool:
        signature = tool_call_signature(name, args)
        signatures = [*recent_tool_signatures, signature]
        status = classify_loop(signatures, signature, self._control_settings)
        if status == "warn":
            warning = f"Loop warning: repeated tool call detected for {name}. Change strategy if this keeps failing."
            self._audit_log.push("loop", warning)
            events.put_nowait(AgentNotice(warning))
            return False
        if status == "block":
            warning = f"Loop blocked: repeated tool call limit reached for {name}."
            self._audit_log.push("loop", warning)
            events.put_nowait(AgentNotice(warning))
            return True
        return False

    def _record_control_plane_success(self, name: str, args: object) -> None:
        signature = tool_call_signature(name, args)
        self._audit_log.push("tool", f"{name}: {_tool_detail(args)}")
        if is_verification_tool(name, args):
            self._audit_log.push("verify", f"Verification step observed via {name}")
        if is_mutating_tool(name, args):
            self._audit_log.push("mutate", f"Mutation step observed via {name}")

    def _todo_event(self) -> AgentTodoUpdate:
        items = self._todo_board.items()
        completed = sum(1 for item in items if item.status == "done")
        return AgentTodoUpdate(
            message=self._todo_board.notice(),
            total=len(items),
            completed=completed,
        )

    @staticmethod
    def _mutation_since_last_verification(messages: list[Message]) -> bool:
        mutated = False
        for message in messages:
            if message.kind != "assistant" or message.turn is None:
                continue
            for call in message.turn.tool_calls:
                if is_mutating_tool(call.name, call.arguments):
                    mutated = True
                elif mutated and is_verification_tool(call.name, call.arguments):
                    mutated = False
        return mutated


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


def _tool_detail(args: object) -> str:
    if not isinstance(args, dict):
        return "task"
    for key in ("task", "description", "path", "command", "question"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if len(text) > 80:
                return text[:77] + "..."
            return text
    items = args.get("items", args.get("todos"))
    if isinstance(items, list):
        return f"{len(items)} item(s)"
    return "task"
