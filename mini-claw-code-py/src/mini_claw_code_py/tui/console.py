from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from mini_claw_code_py import (
    AgentApprovalUpdate,
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
    SessionRecord,
    SessionStore,
    UserInputRequest,
    render_runtime_status,
    render_surface_block,
    surface_block_for_event,
)

from . import theme


STRUCTURED_EVENT_TYPES: Final = (
    AgentTokenUsage,
    AgentTodoUpdate,
    AgentSubagentUpdate,
    AgentApprovalUpdate,
    AgentMemoryUpdate,
    AgentContextCompaction,
)
DEFAULT_COMMAND_ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("/help", "show available commands"),
    ("/plan", "toggle planning mode"),
    ("/status", "show runtime status"),
    ("/todos", "show todo state"),
    ("/session", "show current session"),
    ("/sessions", "show recent sessions and select one to resume"),
    ("/audit", "show audit log"),
    ("/new", "start a fresh session"),
    ("/resume <id>", "resume a saved session"),
    ("/quit", "exit the CLI"),
)


@dataclass(slots=True)
class ToolRenderDecision:
    show: bool
    message: str


class SpinnerStatus:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None
        self._message = "Working..."

    def start(self, message: str) -> None:
        self._message = message
        if self._live is not None:
            self._live.update(self._renderable())
            return
        self._live = Live(
            self._renderable(),
            console=self._console,
            transient=True,
            refresh_per_second=12,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live is None:
            return
        self._live.stop()
        self._live = None

    def _renderable(self) -> Spinner:
        return Spinner(
            "dots",
            text=Text(f" {self._message}", style=theme.MUTED),
            style=theme.SPINNER,
        )


def command_rows() -> tuple[tuple[str, str], ...]:
    return DEFAULT_COMMAND_ROWS


def resolve_option_answer(answer: str, options: list[str]) -> str:
    stripped = answer.strip()
    if stripped.isdigit():
        index = int(stripped)
        if 1 <= index <= len(options):
            return options[index - 1]
    return stripped


def resolve_session_selection(answer: str, session_ids: list[str]) -> str | None:
    stripped = answer.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        index = int(stripped)
        if 1 <= index <= len(session_ids):
            return session_ids[index - 1]
    return stripped


def summarize_tool_call(
    *,
    tool_count: int,
    summary: str,
    name: str,
    collapse_after: int,
    always_show: set[str],
    collapsed_tools_reported: bool,
) -> ToolRenderDecision:
    if tool_count <= collapse_after or name in always_show:
        return ToolRenderDecision(show=True, message=summary)
    if collapsed_tools_reported:
        return ToolRenderDecision(show=False, message="")
    return ToolRenderDecision(show=True, message="additional tool calls omitted")


class ConsoleUI:
    def __init__(
        self,
        *,
        console: Console | None = None,
        collapse_after: int = 4,
    ) -> None:
        self.console = console or Console()
        self.collapse_after = collapse_after
        self._always_show_tools = {"subagent", "write_todos"}

    def print_banner(self, *, cwd: str, session_id: str) -> None:
        info = Table.grid(padding=(0, 1))
        info.add_column(style=theme.MUTED, width=10)
        info.add_column()
        info.add_row("workspace", cwd)
        info.add_row("session", session_id)
        info.add_row("hint", "Use /help for commands. Press Ctrl-D or /quit to exit.")
        self.console.print(
            Panel(
                info,
                title=Text("mini-claw-code", style=theme.TITLE),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print()

    def print_help(self) -> None:
        table = Table(box=box.SIMPLE_HEAVY, border_style=theme.BORDER, show_header=False)
        table.add_column(style=theme.PRIMARY_BOLD, no_wrap=True)
        table.add_column(style="")
        for command, description in command_rows():
            table.add_row(command, description)
        self.console.print(
            Panel(
                table,
                title=Text("Commands", style=theme.PRIMARY_BOLD),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print()

    def read_prompt(self, *, plan_mode: bool) -> str:
        prompt = (
            f"[{theme.PLAN}]plan[/] [bold {theme.PRIMARY}]›[/] "
            if plan_mode
            else f"[bold {theme.PRIMARY}]›[/] "
        )
        return self.console.input(prompt).strip()

    def read_plan_approval(self) -> str:
        prompt = f"[{theme.SUCCESS}]approve[/] [bold {theme.PRIMARY}]›[/] "
        return self.console.input(prompt).strip()

    def print_mode_change(self, *, plan_mode: bool) -> None:
        state = "ON" if plan_mode else "OFF"
        self._print_line("mode", f"planning {state}", style=theme.SUCCESS if plan_mode else theme.MUTED)
        if plan_mode:
            self._print_line(
                "note",
                "planning is read-only: the agent can inspect, ask questions, and update todos, but it will not edit files or run subagents.",
            )
        self.console.print()

    def print_runtime_status(self, agent: object, *, plan_mode: bool) -> None:
        lines = render_runtime_status(
            mode="planning" if plan_mode else "execution",
            control_profile=agent.control_plane_profile_name(),
            todo_text=agent.todo_board().render(),
            token_usage_text=agent.token_usage_tracker().render(),
        )
        self._print_lines_panel("Runtime", lines)

    def print_audit_log(self, agent: object) -> None:
        self._print_lines_panel("Audit Log", agent.audit_log().render().splitlines())

    def print_session_status(self, session: SessionRecord) -> None:
        table = Table.grid(padding=(0, 1))
        table.add_column(style=theme.MUTED, width=8)
        table.add_column()
        table.add_row("id", session.id)
        table.add_row("title", session.title)
        table.add_row("updated", session.updated_at)
        self.console.print(
            Panel(
                table,
                title=Text("Session", style=theme.PRIMARY_BOLD),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print()

    def print_session_list(self, store: SessionStore, *, limit: int = 10) -> list[SessionRecord]:
        records = store.list_recent(limit=limit)
        if not records:
            self._print_line("note", "No saved sessions yet.")
            self.console.print()
            return []

        table = Table(box=box.SIMPLE_HEAVY, border_style=theme.BORDER)
        table.add_column("#", style=theme.MUTED, no_wrap=True, width=3)
        table.add_column("ID", style=theme.PRIMARY_BOLD, no_wrap=True)
        table.add_column("Title")
        table.add_column("Updated", style=theme.MUTED, no_wrap=True)
        for index, record in enumerate(records, start=1):
            table.add_row(str(index), record.id, record.title, record.updated_at)
        self.console.print(
            Panel(
                table,
                title=Text("Recent Sessions", style=theme.PRIMARY_BOLD),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self._print_line("hint", "Enter a row number or session id to resume. Press Enter to cancel.")
        self.console.print()
        return records

    def read_session_selection(self, records: list[SessionRecord]) -> str | None:
        session_id = resolve_session_selection(
            self.console.input(f"[bold {theme.PRIMARY}]resume session ›[/] "),
            [record.id for record in records],
        )
        self.console.print()
        return session_id

    def print_plan_rejected(self, plan_text: str) -> None:
        self.console.print(
            Panel(
                Text(plan_text),
                title=Text("Plan Rejected", style=theme.WARNING),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print()

    def print_started_session(self, session_id: str) -> None:
        self._print_line("session", f"started {session_id}", style=theme.SUCCESS)
        self.console.print()

    def print_resumed_session(self, session: SessionRecord) -> None:
        self._print_line("session", f"resumed {session.id} | {session.title}", style=theme.SUCCESS)
        self.console.print()

    def print_usage(self, message: str) -> None:
        self._print_line("usage", message, style=theme.WARNING)
        self.console.print()

    def print_unknown_session(self, session_id: str) -> None:
        self._print_line("error", f"unknown session: {session_id}", style=theme.ERROR)
        self.console.print()

    def print_unknown_command(self, command: str) -> None:
        self._print_line("error", f"unknown command: {command}", style=theme.ERROR)
        self._print_line("hint", "use /help to see supported commands")
        self.console.print()

    def drain_notice_queue(self, queue: "asyncio.Queue[object]") -> None:
        last_structured_message: str | None = None
        while not queue.empty():
            event = queue.get_nowait()
            if isinstance(event, STRUCTURED_EVENT_TYPES):
                block = surface_block_for_event(event)
                if block is None:
                    self._print_line("note", event.message)
                else:
                    self._print_surface_block(block.kind, render_surface_block(block))
                last_structured_message = getattr(event, "message", None)
                continue
            if isinstance(event, AgentNotice):
                if last_structured_message == event.message:
                    last_structured_message = None
                    continue
                self._print_line("note", event.message)
        if last_structured_message is not None:
            self.console.print()

    async def handle_input_request(self, req: UserInputRequest) -> None:
        answer = await asyncio.to_thread(self._read_input_request, req)
        req.response_future.set_result(answer)

    async def run_agent_stream(
        self,
        queue: "asyncio.Queue[object]",
        input_queue: "asyncio.Queue[UserInputRequest]",
        *,
        spinner_label: str,
    ) -> None:
        spinner = SpinnerStatus(self.console)
        spinner.start(spinner_label)
        tool_count = 0
        collapsed_tools_reported = False
        streaming_text = False
        last_structured_message: str | None = None

        while True:
            agent_task = asyncio.create_task(queue.get())
            input_task = asyncio.create_task(input_queue.get())

            done, pending = await asyncio.wait(
                [agent_task, input_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            if input_task in done:
                if streaming_text:
                    self.console.file.write("\n")
                    self.console.file.flush()
                    streaming_text = False
                spinner.stop()
                await self.handle_input_request(input_task.result())
                spinner.start(spinner_label)
                continue

            event = agent_task.result()
            if isinstance(event, AgentTextDelta):
                if not streaming_text:
                    spinner.stop()
                    self.console.print(Text("assistant", style=theme.PRIMARY_BOLD), end=" ")
                    streaming_text = True
                self.console.file.write(event.text)
                self.console.file.flush()
                continue

            if streaming_text:
                self.console.file.write("\n")
                self.console.file.flush()
                streaming_text = False

            if isinstance(event, AgentToolCall):
                spinner.stop()
                tool_count += 1
                decision = summarize_tool_call(
                    tool_count=tool_count,
                    summary=event.summary,
                    name=event.name,
                    collapse_after=self.collapse_after,
                    always_show=self._always_show_tools,
                    collapsed_tools_reported=collapsed_tools_reported,
                )
                if decision.show:
                    if decision.message == "additional tool calls omitted":
                        collapsed_tools_reported = True
                    self._print_line("tool", decision.message, style=theme.TOOL)
                spinner.start(spinner_label)
                continue

            if isinstance(event, AgentNotice):
                spinner.stop()
                if last_structured_message != event.message:
                    self._print_line("note", event.message)
                else:
                    last_structured_message = None
                spinner.start(spinner_label)
                continue

            if isinstance(event, STRUCTURED_EVENT_TYPES):
                spinner.stop()
                block = surface_block_for_event(event)
                if block is None:
                    self._print_line("note", event.message)
                else:
                    self._print_surface_block(block.kind, render_surface_block(block))
                last_structured_message = getattr(event, "message", None)
                spinner.start(spinner_label)
                continue

            if isinstance(event, AgentDone):
                spinner.stop()
                self.console.print()
                return

            if isinstance(event, AgentError):
                spinner.stop()
                self._print_line("error", event.error, style=theme.ERROR)
                self.console.print()
                return

    def _read_input_request(self, req: UserInputRequest) -> str:
        content = Table.grid(padding=(0, 1))
        content.add_column()
        content.add_row(Text(req.question))
        if req.options:
            for index, option in enumerate(req.options, start=1):
                content.add_row(Text(f"{index}. {option}", style=theme.MUTED))
            content.add_row(Text("Enter a number or free-form answer.", style=theme.MUTED))
        self.console.print(
            Panel(
                content,
                title=Text("Input Required", style=theme.WARNING),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        answer = self.console.input(f"[bold {theme.PRIMARY}]answer ›[/] ")
        self.console.print()
        if req.options:
            return resolve_option_answer(answer, req.options)
        return answer.strip()

    def _print_surface_block(self, kind: str, lines: list[str]) -> None:
        if not lines:
            return
        self._print_line(kind, lines[0], style=theme.MUTED)
        for line in lines[1:]:
            self._print_line("", line, style=theme.MUTED)

    def _print_line(self, label: str, message: str, *, style: str = theme.MUTED) -> None:
        grid = Table.grid(padding=(0, 1))
        grid.add_column(style=theme.LABEL, width=9, no_wrap=True)
        grid.add_column(style=style)
        grid.add_row(label, message)
        self.console.print(grid)

    def _print_lines_panel(self, title: str, lines: list[str]) -> None:
        body: RenderableType
        if lines:
            group = Group(*(Text(line) for line in lines))
            body = group
        else:
            body = Text("No data.", style=theme.MUTED)
        self.console.print(
            Panel(
                body,
                title=Text(title, style=theme.PRIMARY_BOLD),
                border_style=theme.BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print()
