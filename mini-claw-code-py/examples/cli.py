from __future__ import annotations

import asyncio
from pathlib import Path

from mini_claw_code_py import (
    AgentDone,
    AgentError,
    AgentNotice,
    AgentTextDelta,
    AgentToolCall,
    ChannelInputHandler,
    DEFAULT_PLAN_PROMPT_TEMPLATE,
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    HarnessAgent,
    Message,
    OpenRouterProvider,
    SYSTEM_PROMPT_FILE_ENV,
    UserInputRequest,
    load_prompt_template,
    render_system_prompt,
)

SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
SPINNER_INTERVAL = 0.08
COLLAPSE_AFTER = 3

BOLD_CYAN = "\x1b[1;36m"
BOLD_MAGENTA = "\x1b[1;35m"
BOLD_GREEN = "\x1b[1;32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
CLEAR_LINE = "\x1b[2K\r"


def spinner_line(frame: int, label: str) -> str:
    ch = SPINNER[frame % len(SPINNER)]
    return f"{BOLD_MAGENTA}⏺{RESET} {YELLOW}{ch} {label}{RESET}"


def render_tool_line(tool_count: int, summary: str) -> str:
    if tool_count <= COLLAPSE_AFTER:
        return f"  {DIM}⎿  {summary}{RESET}\n"
    extra = tool_count - COLLAPSE_AFTER
    suffix = "more" if extra > 1 else "more"
    return f"  {DIM}⎿  ... and {extra} {suffix}{RESET}\n"


def prompt_prefix(plan_mode: bool) -> str:
    if plan_mode:
        return f"{BOLD_GREEN}[plan]{RESET} {BOLD_CYAN}>{RESET} "
    return f"{BOLD_CYAN}>{RESET} "


def read_option_answer(req: UserInputRequest) -> str:
    print()
    print(f"  {BOLD_CYAN}{req.question}{RESET}")
    for index, option in enumerate(req.options, start=1):
        print(f"    {index}) {option}")
    answer = input("  > ").strip()
    if answer.isdigit():
        number = int(answer)
        if 1 <= number <= len(req.options):
            return req.options[number - 1]
    return answer


def read_text_answer(req: UserInputRequest) -> str:
    print()
    print(f"  {BOLD_CYAN}{req.question}{RESET}")
    return input("  > ").strip()


async def handle_input_request(req: UserInputRequest) -> None:
    if req.options:
        answer = await asyncio.to_thread(read_option_answer, req)
    else:
        answer = await asyncio.to_thread(read_text_answer, req)
    req.response_future.set_result(answer)


async def ui_event_loop(
    queue: "asyncio.Queue[object]",
    input_queue: "asyncio.Queue[UserInputRequest]",
    *,
    spinner_label: str,
) -> None:
    frame = 0
    tool_count = 0
    collapsed_tools_reported = False
    streaming_text = False

    print(spinner_line(frame, spinner_label), end="", flush=True)

    while True:
        agent_task = asyncio.create_task(queue.get())
        input_task = asyncio.create_task(input_queue.get())
        tick_task = asyncio.create_task(asyncio.sleep(SPINNER_INTERVAL))

        done, pending = await asyncio.wait(
            [agent_task, input_task, tick_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        if tick_task in done:
            if not streaming_text:
                frame += 1
                print(f"\r{spinner_line(frame, spinner_label)}", end="", flush=True)
            continue

        if input_task in done:
            print(CLEAR_LINE, end="", flush=True)
            streaming_text = False
            await handle_input_request(input_task.result())
            print(spinner_line(frame, spinner_label), end="", flush=True)
            continue

        event = agent_task.result()
        if isinstance(event, AgentTextDelta):
            if not streaming_text:
                print(CLEAR_LINE, end="", flush=True)
                streaming_text = True
            print(event.text, end="", flush=True)
        elif isinstance(event, AgentToolCall):
            tool_count += 1
            streaming_text = False
            print(CLEAR_LINE, end="", flush=True)
            if tool_count <= COLLAPSE_AFTER or event.name in {"subagent", "write_todos"}:
                print(render_tool_line(tool_count, event.summary), end="", flush=True)
            elif not collapsed_tools_reported:
                collapsed_tools_reported = True
                print(f"  {DIM}⎿  ... additional tool calls omitted ...{RESET}\n", end="", flush=True)
            print(spinner_line(frame, spinner_label), end="", flush=True)
        elif isinstance(event, AgentNotice):
            streaming_text = False
            print(CLEAR_LINE, end="", flush=True)
            print(f"  {DIM}{event.message}{RESET}")
            print(spinner_line(frame, spinner_label), end="", flush=True)
        elif isinstance(event, AgentDone):
            print(CLEAR_LINE, end="", flush=True)
            print()
            return
        elif isinstance(event, AgentError):
            print(CLEAR_LINE, end="", flush=True)
            print(f"{BOLD_MAGENTA}⏺{RESET} {RED}error: {event.error}{RESET}\n")
            return


def drain_notice_queue(queue: "asyncio.Queue[AgentNotice]") -> None:
    while not queue.empty():
        notice = queue.get_nowait()
        print(f"  {DIM}{notice.message}{RESET}")


def print_runtime_status(agent: HarnessAgent, *, plan_mode: bool) -> None:
    mode = "planning" if plan_mode else "execution"
    print(f"  {DIM}Mode: {mode}{RESET}")
    print(f"  {DIM}{agent.todo_board().render()}{RESET}")
    print()


async def main() -> None:
    provider = OpenRouterProvider.from_env()
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    event_queue: asyncio.Queue[object] = asyncio.Queue()
    cwd = Path.cwd()

    system_prompt = render_system_prompt(
        load_prompt_template(
            SYSTEM_PROMPT_FILE_ENV,
            DEFAULT_SYSTEM_PROMPT_TEMPLATE,
        ),
        cwd=cwd,
    )
    plan_prompt = render_system_prompt(
        DEFAULT_PLAN_PROMPT_TEMPLATE,
        cwd=cwd,
    )

    agent = (
        HarnessAgent(provider)
        .system_prompt(system_prompt)
        .plan_prompt(plan_prompt)
        .enable_core_tools(ChannelInputHandler(input_queue))
        .enable_workspace(
            cwd,
            scratch=cwd / ".agent-work",
            outputs=cwd / "outputs",
        )
        .enable_default_memory(cwd=cwd)
        .enable_user_memory_file(Path.home() / ".agents" / "AGENTS.md")
        .enable_memory_updates(debounce_seconds=2.0, target_scope="user")
        .enable_context_durability()
        .enable_subagents(max_parallel_subagents=2)
        .enable_default_mcp(cwd=cwd)
        .enable_tool_universe_management()
        .enable_default_skills(cwd)
    )

    history: list[Message] = []
    plan_mode = False
    print()

    while True:
        drain_notice_queue(agent.notice_queue())
        try:
            prompt = input(prompt_prefix(plan_mode)).strip()
        except EOFError:
            await agent.flush_memory_updates()
            drain_notice_queue(agent.notice_queue())
            print()
            return

        if not prompt:
            continue
        if prompt == "/plan":
            plan_mode = not plan_mode
            state = "ON" if plan_mode else "OFF"
            print(f"  {DIM}Plan mode {state}{RESET}")
            if plan_mode:
                print(
                    f"  {DIM}Planning is read-only: the agent can inspect, ask questions, and update todos, but it will not edit files or run subagents.{RESET}\n"
                )
            else:
                print()
            continue
        if prompt in {"/status", "/todos"}:
            print_runtime_status(agent, plan_mode=plan_mode)
            continue

        if not plan_mode and agent.todo_board().all_completed():
            agent.todo_board().clear()
        history.append(Message.user(prompt))
        print()

        if plan_mode:
            while True:
                worker = asyncio.create_task(agent.plan(history, event_queue))
                await ui_event_loop(event_queue, input_queue, spinner_label="Planning...")
                plan_text = await worker

                approval = input(
                    f"  {BOLD_GREEN}Accept this plan?{RESET} {DIM}[y/n/feedback]{RESET} "
                ).strip()
                print()

                if approval.lower() == "y":
                    event_queue = asyncio.Queue()
                    history.append(Message.user("Proceed with the approved plan."))
                    worker = asyncio.create_task(agent.execute(history, event_queue))
                    await ui_event_loop(event_queue, input_queue, spinner_label="Executing...")
                    await worker
                    break
                if approval.lower() in {"n", "no"}:
                    print(f"{DIM}Plan rejected:{RESET}\n{plan_text}\n")
                    break

                history.append(Message.user(f"Revise the plan with this feedback: {approval}"))
        else:
            worker = asyncio.create_task(agent.execute(history, event_queue))
            await ui_event_loop(event_queue, input_queue, spinner_label="Thinking...")
            await worker


if __name__ == "__main__":
    asyncio.run(main())
