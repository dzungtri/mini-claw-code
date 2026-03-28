from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from rich.console import Console
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from mini_claw_code_py import (
    AgentApprovalUpdate,
    AgentArtifactUpdate,
    AgentContextCompaction,
    AgentDone,
    AgentError,
    AgentMemoryUpdate,
    AgentNotice,
    AgentSubagentUpdate,
    AgentTextDelta,
    AgentTodoUpdate,
    AgentTokenUsage,
    AgentToolCall,
    GoalStore,
    HarnessAgent,
    HostedAgentFactory,
    HostedAgentRegistry,
    Message,
    MessageEnvelope,
    OpenRouterProvider,
    RunStore,
    SessionRoute,
    SessionRecord,
    SessionStore,
    SessionWorkStore,
    SessionRouter,
    TaskStore,
    TeamRegistry,
    TurnRunner,
    UserInputRequest,
    default_os_state_root,
    default_route_store,
)

from .app import (
    CLI_TARGET_AGENT,
    CLI_THREAD_KEY,
    _resume_session,
    _save_session,
    _shutdown,
    build_agent,
)
from .console import (
    ConsoleUI,
    command_rows,
    resolve_option_answer,
    resolve_session_selection,
    summarize_history_message,
    summarize_tool_call,
)


STRUCTURED_EVENT_TYPES = (
    AgentTokenUsage,
    AgentTodoUpdate,
    AgentSubagentUpdate,
    AgentApprovalUpdate,
    AgentArtifactUpdate,
    AgentMemoryUpdate,
    AgentContextCompaction,
)


class WorkApp(App[None]):
    TITLE = "mini-claw-code"
    SUB_TITLE = "work console"
    CSS = """
    Screen {
        layout: vertical;
    }

    #summary {
        height: auto;
        border: round $accent;
        padding: 0 1;
        margin: 0 1;
    }

    #body {
        height: 1fr;
        layout: horizontal;
        margin: 0 1;
    }

    #transcript {
        width: 2fr;
        border: round $panel;
        padding: 0 1;
    }

    #sidebar {
        width: 1fr;
        border: round $panel;
        padding: 0 1;
        margin-left: 1;
    }

    #live_output {
        height: 8;
        border: round $warning;
        padding: 0 1;
        margin: 0 1;
    }

    #command {
        dock: bottom;
        margin: 0 1 1 1;
    }
    """
    BINDINGS = [
        Binding("ctrl+q", "request_quit", "Quit"),
        Binding("ctrl+l", "clear_transcript", "Clear"),
        Binding("/", "focus_command", "Command"),
    ]

    def __init__(
        self,
        *,
        provider: Any,
        cwd: Path,
        home: Path,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.cwd = cwd.expanduser().resolve()
        self.home = home.expanduser().resolve()

        self.input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
        self.store = SessionStore(self.cwd / ".mini-claw" / "sessions")
        self.router = SessionRouter(default_route_store(self.cwd), self.store)
        self.runs = RunStore(default_os_state_root(self.cwd))
        self.teams = TeamRegistry.discover_default(cwd=self.cwd, home=self.home)
        self.goals = GoalStore(default_os_state_root(self.cwd))
        self.tasks = TaskStore(default_os_state_root(self.cwd))
        self.session_work = SessionWorkStore(default_os_state_root(self.cwd))
        self.registry = HostedAgentRegistry.discover_default(cwd=self.cwd, home=self.home)
        self.factory = HostedAgentFactory(
            provider=provider,  # type: ignore[arg-type]
            home=self.home,
            input_queue=self.input_queue,
        )
        self.runner = TurnRunner(
            registry=self.registry,
            factory=self.factory,
            router=self.router,
            sessions=self.store,
            runs=self.runs,
            teams=self.teams,
            goals=self.goals,
            tasks=self.tasks,
            session_work=self.session_work,
        )

        self.agent: HarnessAgent = build_agent(
            provider,  # type: ignore[arg-type]
            cwd=self.cwd,
            input_queue=self.input_queue,
            home=self.home,
        )
        self.current_route: SessionRoute
        self.current_session: SessionRecord
        self.history: list[Message] = []
        self.plan_mode = False
        self.pending_plan_text: str | None = None
        self.pending_session_ids: list[str] | None = None
        self.pending_user_request: UserInputRequest | None = None
        self.active_run_task: asyncio.Task[None] | None = None
        self._stream_buffer = ""
        self._collapsed_tools_reported = False
        self._tool_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        with Horizontal(id="body"):
            yield RichLog(id="transcript", wrap=True, highlight=False, auto_scroll=True)
            yield Static(id="sidebar")
        yield Static(id="live_output")
        yield Input(placeholder="Type a message or /help", id="command")
        yield Footer()

    def on_mount(self) -> None:
        self.current_route, self.current_session = self.router.resolve_or_create(
            target_agent=CLI_TARGET_AGENT,
            thread_key=CLI_THREAD_KEY,
            cwd=self.cwd,
        )
        self.history = self.store.restore_into_agent(self.agent, self.current_session)
        self._append_block(
            "Session",
            f"workspace={self.cwd}\nsession={self.current_session.id}\nhint=Use /help for commands. Ctrl+Q quits.",
        )
        if self.history:
            self._append_history_preview()
        self._set_live_output("")
        self._refresh_status()
        self.query_one("#command", Input).focus()

    def action_request_quit(self) -> None:
        self.exit()

    def action_clear_transcript(self) -> None:
        self.query_one("#transcript", RichLog).clear()

    def action_focus_command(self) -> None:
        command = self.query_one("#command", Input)
        if not command.value:
            command.value = "/"
        elif not command.value.startswith("/"):
            command.value = f"/{command.value}"
        command.cursor_position = len(command.value)
        command.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return

        if self.pending_user_request is not None:
            self._resolve_user_request(value)
            return

        if self.pending_session_ids is not None and not value.startswith("/"):
            await self._resolve_session_selection(value)
            return

        if self.pending_plan_text is not None and not value.startswith("/"):
            await self._handle_plan_response(value)
            return

        if value.startswith("/"):
            await self._handle_command(value)
            return

        if self.active_run_task is not None and not self.active_run_task.done():
            self.notify("A run is already in progress.")
            return

        await self._start_execution(value)

    async def _handle_command(self, prompt: str) -> None:
        if prompt in {"/quit", "/exit"}:
            await _shutdown(self.agent, self._recording_ui())
            self.action_request_quit()
            return
        if prompt == "/help":
            self._append_block("Commands", "\n".join(f"{cmd} - {desc}" for cmd, desc in command_rows()))
            return
        if prompt == "/plan":
            self.plan_mode = not self.plan_mode
            self._append_block(
                "Mode",
                "planning ON\nplanning is read-only: inspect, ask questions, and update todos, but do not edit files or run subagents."
                if self.plan_mode
                else "planning OFF",
            )
            self._refresh_status()
            return
        if prompt in {"/status", "/todos"}:
            self._append_rendered("Runtime", "print_runtime_status", self.agent, plan_mode=self.plan_mode)
            return
        if prompt == "/artifacts":
            self._append_rendered("Artifacts", "print_artifacts", self.agent)
            return
        if prompt == "/mcp":
            self._append_rendered("MCP", "print_mcp", self.agent)
            return
        if prompt == "/subagents":
            self._append_rendered("Subagents", "print_subagents", self.agent)
            return
        if prompt == "/agents":
            self._append_rendered(
                "Hosted Agents",
                "print_agents",
                self.registry,
                current_agent=self.current_route.target_agent,
            )
            return
        if prompt == "/teams":
            self._append_rendered("Teams", "print_teams", self.teams)
            return
        if prompt == "/work":
            self._append_rendered(
                "Work",
                "print_work_status",
                session_id=self.current_session.id,
                binding=self.session_work.get(self.current_session.id),
                goals=self.goals,
                tasks=self.tasks,
            )
            return
        if prompt == "/goals":
            self._append_rendered("Goals", "print_goals", self.goals)
            return
        if prompt == "/tasks":
            self._append_rendered("Tasks", "print_tasks", self.tasks)
            return
        if prompt == "/routes":
            self._append_rendered("Routes", "print_routes", self.router.routes)
            return
        if prompt == "/runs":
            self._append_rendered("Runs", "print_runs", self.runs)
            return
        if prompt == "/session":
            self._append_rendered(
                "Session",
                "print_session_status",
                self.current_session,
                route=self.current_route,
                binding=self.session_work.get(self.current_session.id),
            )
            return
        if prompt == "/sessions":
            self.pending_session_ids = [record.id for record in self.store.list_recent(limit=10)]
            self._append_rendered("Sessions", "print_session_list", self.store, limit=10)
            if self.pending_session_ids:
                self._append_block("Input", "Enter a session number or session id to resume it.")
            return
        if prompt.startswith("/rename"):
            parts = prompt.split(maxsplit=1)
            if len(parts) != 2:
                self._append_block("Usage", "/rename <title>")
                return
            self.current_session = self.store.rename(self.current_session, parts[1])
            self._append_rendered("Session", "print_renamed_session", self.current_session)
            self._refresh_status()
            return
        if prompt.startswith("/fork"):
            self.current_session = _save_session(self.store, self.current_session, self.history, self.agent)
            source_session = self.current_session
            parts = prompt.split(maxsplit=1)
            self.current_session = self.store.fork(
                self.current_session,
                title=parts[1] if len(parts) == 2 else None,
            )
            self.current_route = self.router.bind(
                target_agent=self.current_route.target_agent,
                thread_key=self.current_route.thread_key,
                session_id=self.current_session.id,
            )
            self._append_rendered("Session", "print_forked_session", source_session, self.current_session)
            self._refresh_status()
            return
        if prompt == "/audit":
            self._append_rendered("Audit", "print_audit_log", self.agent)
            return
        if prompt == "/new":
            await self.agent.flush_memory_updates()
            self.agent = build_agent(
                self.provider,  # type: ignore[arg-type]
                cwd=self.cwd,
                input_queue=self.input_queue,
                home=self.home,
            )
            self.history = []
            self.current_session = self.store.persist(self.store.create(cwd=self.cwd))
            self.current_route = self.router.bind(
                target_agent=self.current_route.target_agent,
                thread_key=self.current_route.thread_key,
                session_id=self.current_session.id,
            )
            self.plan_mode = False
            self.pending_plan_text = None
            self._append_rendered("Session", "print_started_session", self.current_session.id)
            self._refresh_status()
            return
        if prompt.startswith("/resume"):
            parts = prompt.split(maxsplit=1)
            if len(parts) != 2:
                self._append_block("Usage", "/resume <session_id>")
                return
            await self._resume_to_session(parts[1].strip())
            return
        self._append_block("Command", f"Unknown command: {prompt}")

    async def _resolve_session_selection(self, raw: str) -> None:
        assert self.pending_session_ids is not None
        session_id = resolve_session_selection(raw, self.pending_session_ids)
        self.pending_session_ids = None
        if session_id is None:
            self._append_block("Sessions", "Selection cancelled.")
            return
        await self._resume_to_session(session_id)

    async def _resume_to_session(self, session_id: str) -> None:
        try:
            _, self.agent, self.current_route, self.current_session, self.history, self.plan_mode = await _resume_session(
                session_id=session_id,
                provider=self.provider,  # type: ignore[arg-type]
                input_queue=self.input_queue,
                store=self.store,
                router=self.router,
                agent=self.agent,
                current_route=self.current_route,
                current_session=self.current_session,
                history=self.history,
                plan_mode=self.plan_mode,
                ui=self._recording_ui(),
            )
        except Exception as exc:
            self._append_block("Session", f"Failed to resume {session_id}: {exc}")
            return
        self._append_block("Session", f"Resumed {self.current_session.id}")
        self._append_history_preview()
        self._refresh_status()

    async def _start_execution(self, prompt: str) -> None:
        if self.plan_mode:
            self.history.append(Message.user(prompt))
            self._append_block("User", prompt)
            self.active_run_task = asyncio.create_task(self._run_plan(prompt))
            return

        self._append_block("User", prompt)
        self.active_run_task = asyncio.create_task(self._run_execution(prompt))

    async def _run_execution(self, prompt: str) -> None:
        self._set_busy(True)
        self._reset_stream_tracking()
        event_queue: asyncio.Queue[object] = asyncio.Queue()
        runner_task = asyncio.create_task(
            self.runner.run(
                MessageEnvelope(
                    source="cli",
                    target_agent=self.current_route.target_agent,
                    thread_key=self.current_route.thread_key,
                    kind="user_message",
                    content=prompt,
                ),
                event_queue,
            )
        )
        request_task = asyncio.create_task(self._drain_user_requests(runner_task))
        event_task = asyncio.create_task(self._drain_agent_events(event_queue))
        try:
            result = await runner_task
            self.agent = result.agent
            self.history = result.history
            self.current_route = result.context.route
            self.current_session = result.context.session
        except Exception as exc:
            self._append_block("Error", str(exc))
        finally:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
            await event_task
            self._set_busy(False)
            self._refresh_status()

    async def _run_plan(self, prompt: str) -> None:
        self._set_busy(True)
        self._reset_stream_tracking()
        event_queue: asyncio.Queue[object] = asyncio.Queue()
        worker = asyncio.create_task(self.agent.plan(self.history, event_queue))
        request_task = asyncio.create_task(self._drain_user_requests(worker))
        event_task = asyncio.create_task(self._drain_agent_events(event_queue))
        try:
            plan_text = await worker
            self.pending_plan_text = plan_text
            self.current_session = _save_session(self.store, self.current_session, self.history, self.agent)
            self._append_block("Plan", plan_text)
            self._append_block("Approval", "Reply with y / n / feedback.")
        except Exception as exc:
            self._append_block("Error", str(exc))
        finally:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
            await event_task
            self._set_busy(False)
            self._refresh_status()

    async def _handle_plan_response(self, value: str) -> None:
        approval = value.strip()
        if approval.lower() == "y":
            self.pending_plan_text = None
            self.history.append(Message.user("Proceed with the approved plan."))
            self._append_block("User", "Proceed with the approved plan.")
            self.active_run_task = asyncio.create_task(self._run_plan_execution())
            return
        if approval.lower() in {"n", "no"}:
            self._append_block("Plan", "Plan rejected.")
            self.pending_plan_text = None
            return
        self.pending_plan_text = None
        self.history.append(Message.user(f"Revise the plan with this feedback: {approval}"))
        self._append_block("Feedback", approval)
        self.active_run_task = asyncio.create_task(self._run_plan(approval))

    async def _run_plan_execution(self) -> None:
        self._set_busy(True)
        self._reset_stream_tracking()
        event_queue: asyncio.Queue[object] = asyncio.Queue()
        worker = asyncio.create_task(self.agent.execute(self.history, event_queue))
        request_task = asyncio.create_task(self._drain_user_requests(worker))
        event_task = asyncio.create_task(self._drain_agent_events(event_queue))
        try:
            await worker
            self.current_session = _save_session(self.store, self.current_session, self.history, self.agent)
        except Exception as exc:
            self._append_block("Error", str(exc))
        finally:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
            await event_task
            self._set_busy(False)
            self._refresh_status()

    async def _drain_user_requests(self, worker: asyncio.Task[object]) -> None:
        while not worker.done():
            try:
                request = await asyncio.wait_for(self.input_queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            self.pending_user_request = request
            options = "\n".join(f"{index}. {option}" for index, option in enumerate(request.options, start=1))
            text = request.question if not options else f"{request.question}\n{options}"
            self._append_block("Question", text)
            self.query_one("#command", Input).placeholder = "Answer the pending question"

    async def _drain_agent_events(self, queue: asyncio.Queue[object]) -> None:
        while True:
            event = await queue.get()
            if isinstance(event, AgentTextDelta):
                self._stream_buffer += event.text
                self._set_live_output(self._stream_buffer)
                continue
            if isinstance(event, AgentToolCall):
                self._tool_count += 1
                decision = summarize_tool_call(
                    tool_count=self._tool_count,
                    summary=event.summary,
                    name=event.name,
                    collapse_after=4,
                    always_show={"subagent", "write_todos"},
                    collapsed_tools_reported=self._collapsed_tools_reported,
                )
                if decision.show:
                    self._append_block("Tool", decision.message)
                    if decision.message == "additional tool calls omitted":
                        self._collapsed_tools_reported = True
                continue
            if isinstance(event, STRUCTURED_EVENT_TYPES):
                self._append_block("Event", _structured_event_text(event))
                continue
            if isinstance(event, AgentNotice):
                self._append_block("Notice", event.message)
                continue
            if isinstance(event, AgentDone):
                self._set_live_output("")
                self._append_block("Assistant", event.text)
                return
            if isinstance(event, AgentError):
                self._set_live_output("")
                self._append_block("Error", event.error)
                return

    def _resolve_user_request(self, raw: str) -> None:
        assert self.pending_user_request is not None
        request = self.pending_user_request
        self.pending_user_request = None
        answer = resolve_option_answer(raw, request.options)
        if not request.response_future.done():
            request.response_future.set_result(answer)
        self.query_one("#command", Input).placeholder = "Type a message or /help"
        self._append_block("Answer", answer)

    def _refresh_status(self) -> None:
        summary = [
            f"workspace={self.cwd}",
            f"session={self.current_session.id}",
            f"agent={self.current_route.target_agent}",
            f"thread={self.current_route.thread_key}",
            f"mode={'planning' if self.plan_mode else 'execution'}",
        ]
        if self.active_run_task is not None and not self.active_run_task.done():
            summary.append("run_state=busy")
        else:
            summary.append("run_state=idle")
        self.query_one("#summary", Static).update("\n".join(summary))

        binding = self.session_work.get(self.current_session.id)
        sidebar_lines = []
        if binding is None:
            sidebar_lines.append("work=no active binding")
        else:
            sidebar_lines.extend(
                [
                    f"team={binding.team_id}",
                    f"goal={binding.goal_id}",
                    f"task={binding.task_id}",
                ]
            )
            goal = self.goals.get(binding.goal_id)
            task = self.tasks.get(binding.task_id)
            if goal is not None:
                sidebar_lines.append(f"goal_status={goal.status}")
            if task is not None:
                sidebar_lines.append(f"task_status={task.status}")
        sidebar_lines.append("")
        sidebar_lines.extend(
            [
                f"profile={self.agent.control_plane_profile_name()}",
                self.agent.token_usage_tracker().render(),
            ]
        )
        self.query_one("#sidebar", Static).update("\n".join(sidebar_lines))

    def _append_history_preview(self) -> None:
        lines: list[str] = []
        for message in self.history[-8:]:
            summary = summarize_history_message(message)
            if summary is None:
                continue
            kind, text = summary
            lines.append(f"{kind}: {text}")
        if lines:
            self._append_block("History", "\n".join(lines))

    def _append_rendered(self, title: str, method_name: str, *args: Any, **kwargs: Any) -> None:
        ui = self._recording_ui()
        method = getattr(ui, method_name)
        result = method(*args, **kwargs)
        text = ui.console.export_text().strip()
        if text:
            self._append_block(title, text)
        elif isinstance(result, list):
            self._append_block(title, "\n".join(str(item) for item in result))

    def _recording_ui(self) -> ConsoleUI:
        return ConsoleUI(console=Console(record=True, width=120))

    def _append_block(self, title: str, text: str) -> None:
        transcript = self.query_one("#transcript", RichLog)
        transcript.write(f"[{title}]\n{text}\n")

    def _set_live_output(self, text: str) -> None:
        live = self.query_one("#live_output", Static)
        live.display = bool(text)
        live.update(text)

    def _set_busy(self, busy: bool) -> None:
        if not busy:
            self.active_run_task = None
        self._refresh_status()

    def _reset_stream_tracking(self) -> None:
        self._stream_buffer = ""
        self._tool_count = 0
        self._collapsed_tools_reported = False
        self._set_live_output("")


def _structured_event_text(event: object) -> str:
    if isinstance(event, STRUCTURED_EVENT_TYPES):
        return event.message
    return str(event)


def run_cli(*, cwd: Path | None = None) -> None:
    workspace = (cwd or Path.cwd()).resolve()
    provider = OpenRouterProvider.from_env()
    WorkApp(provider=provider, cwd=workspace, home=Path.home()).run()
