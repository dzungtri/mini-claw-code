from __future__ import annotations

import asyncio
from pathlib import Path

from mini_claw_code_py import (
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
    SessionRouter,
    TeamRegistry,
    TurnRunner,
    UserInputRequest,
    default_os_state_root,
    default_route_store,
)

from .console import ConsoleUI


CLI_TARGET_AGENT = "superagent"
CLI_THREAD_KEY = "cli:local"


def build_agent(
    provider: OpenRouterProvider,
    *,
    cwd: Path,
    input_queue: "asyncio.Queue[UserInputRequest]",
) -> HarnessAgent:
    registry = HostedAgentRegistry.discover_default(cwd=cwd, home=Path.home())
    definition = registry.require("superagent")
    return HostedAgentFactory(
        provider=provider,
        home=Path.home(),
        input_queue=input_queue,
    ).build(definition)


async def run_cli(*, cwd: Path | None = None) -> None:
    provider = OpenRouterProvider.from_env()
    workspace = (cwd or Path.cwd()).resolve()
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    store = SessionStore(workspace / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(workspace), store)
    runs = RunStore(default_os_state_root(workspace))
    ui = ConsoleUI()
    registry = HostedAgentRegistry.discover_default(cwd=workspace, home=Path.home())
    factory = HostedAgentFactory(
        provider=provider,
        home=Path.home(),
        input_queue=input_queue,
    )
    runner = TurnRunner(
        registry=registry,
        factory=factory,
        router=router,
        sessions=store,
        runs=runs,
    )

    agent = build_agent(provider, cwd=workspace, input_queue=input_queue)
    current_route, current_session = router.resolve_or_create(
        target_agent=CLI_TARGET_AGENT,
        thread_key=CLI_THREAD_KEY,
        cwd=workspace,
    )
    history = store.restore_into_agent(agent, current_session)
    plan_mode = False

    ui.print_banner(cwd=str(workspace), session_id=current_session.id)
    if history:
        ui.print_history_preview(history)

    while True:
        ui.drain_notice_queue(agent.notice_queue())
        try:
            prompt = ui.read_prompt(plan_mode=plan_mode)
        except EOFError:
            await _shutdown(agent, ui)
            return

        if not prompt:
            continue

        if prompt.startswith("/"):
            handled, agent, current_route, current_session, history, plan_mode = await _handle_command(
                prompt=prompt,
                provider=provider,
                workspace=workspace,
                input_queue=input_queue,
                store=store,
                router=router,
                runs=runs,
                agent=agent,
                current_route=current_route,
                current_session=current_session,
                history=history,
                plan_mode=plan_mode,
                ui=ui,
            )
            if handled:
                if prompt in {"/quit", "/exit"}:
                    return
                continue

        if not plan_mode and agent.todo_board().all_completed():
            agent.todo_board().clear()

        if plan_mode:
            history.append(Message.user(prompt))
            approved, agent, current_session, history = await _run_plan_cycle(
                agent=agent,
                current_session=current_session,
                history=history,
                input_queue=input_queue,
                store=store,
                ui=ui,
            )
            if approved:
                continue
            continue

        event_queue: asyncio.Queue[object] = asyncio.Queue()
        worker = asyncio.create_task(
            runner.run(
                MessageEnvelope(
                    source="cli",
                    target_agent=current_route.target_agent,
                    thread_key=current_route.thread_key,
                    kind="user_message",
                    content=prompt,
                ),
                event_queue,
            )
        )
        await ui.run_agent_stream(event_queue, input_queue, spinner_label="Executing")
        result = await worker
        agent = result.agent
        history = result.history
        current_route = result.context.route
        current_session = result.context.session


async def _handle_command(
    *,
    prompt: str,
    provider: OpenRouterProvider,
    workspace: Path,
    input_queue: "asyncio.Queue[UserInputRequest]",
    store: SessionStore,
    router: SessionRouter,
    runs: RunStore,
    agent: HarnessAgent,
    current_route: SessionRoute,
    current_session: SessionRecord,
    history: list[Message],
    plan_mode: bool,
    ui: ConsoleUI,
) -> tuple[bool, HarnessAgent, SessionRoute, SessionRecord, list[Message], bool]:
    if prompt in {"/quit", "/exit"}:
        await _shutdown(agent, ui)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/help":
        ui.print_help()
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/plan":
        plan_mode = not plan_mode
        ui.print_mode_change(plan_mode=plan_mode)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt in {"/status", "/todos"}:
        ui.print_runtime_status(agent, plan_mode=plan_mode)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/artifacts":
        ui.print_artifacts(agent)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/mcp":
        ui.print_mcp(agent)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/subagents":
        ui.print_subagents(agent)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/agents":
        ui.print_agents(HostedAgentRegistry.discover_default(cwd=workspace, home=Path.home()), current_agent="superagent")
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/teams":
        ui.print_teams(TeamRegistry.discover_default(cwd=workspace, home=Path.home()))
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/routes":
        ui.print_routes(router.routes)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/runs":
        ui.print_runs(runs)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/session":
        ui.print_session_status(current_session, route=current_route)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/sessions":
        records = ui.print_session_list(store)
        if not records:
            return True, agent, current_route, current_session, history, plan_mode
        session_id = ui.read_session_selection(records)
        if session_id is None:
            return True, agent, current_route, current_session, history, plan_mode
        return await _resume_session(
            session_id=session_id,
            provider=provider,
            input_queue=input_queue,
            store=store,
            router=router,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=history,
            plan_mode=plan_mode,
            ui=ui,
        )
    if prompt.startswith("/rename"):
        parts = prompt.split(maxsplit=1)
        if len(parts) != 2:
            ui.print_usage("/rename <title>")
            return True, agent, current_route, current_session, history, plan_mode
        try:
            current_session = store.rename(current_session, parts[1])
        except ValueError as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_renamed_session(current_session)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/fork"):
        current_session = _save_session(store, current_session, history, agent)
        source_session = current_session
        parts = prompt.split(maxsplit=1)
        try:
            current_session = store.fork(
                current_session,
                title=parts[1] if len(parts) == 2 else None,
            )
        except ValueError as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        current_route = router.bind(
            target_agent=current_route.target_agent,
            thread_key=current_route.thread_key,
            session_id=current_session.id,
        )
        ui.print_forked_session(source_session, current_session)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/audit":
        ui.print_audit_log(agent)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/new":
        await agent.flush_memory_updates()
        ui.drain_notice_queue(agent.notice_queue())
        agent = build_agent(provider, cwd=workspace, input_queue=input_queue)
        history = []
        current_session = store.persist(store.create(cwd=workspace))
        current_route = router.bind(
            target_agent=current_route.target_agent,
            thread_key=current_route.thread_key,
            session_id=current_session.id,
        )
        plan_mode = False
        ui.print_started_session(current_session.id)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/resume"):
        parts = prompt.split(maxsplit=1)
        if len(parts) != 2:
            ui.print_usage("/resume <session_id>")
            return True, agent, current_route, current_session, history, plan_mode
        return await _resume_session(
            session_id=parts[1].strip(),
            provider=provider,
            input_queue=input_queue,
            store=store,
            router=router,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=history,
            plan_mode=plan_mode,
            ui=ui,
        )
    if prompt.startswith("/"):
        ui.print_unknown_command(prompt)
        return True, agent, current_route, current_session, history, plan_mode
    return False, agent, current_route, current_session, history, plan_mode


async def _run_plan_cycle(
    *,
    agent: HarnessAgent,
    current_session: SessionRecord,
    history: list[Message],
    input_queue: "asyncio.Queue[UserInputRequest]",
    store: SessionStore,
    ui: ConsoleUI,
) -> tuple[bool, HarnessAgent, SessionRecord, list[Message]]:
    while True:
        event_queue: asyncio.Queue[object] = asyncio.Queue()
        worker = asyncio.create_task(agent.plan(history, event_queue))
        await ui.run_agent_stream(event_queue, input_queue, spinner_label="Planning")
        plan_text = await worker
        current_session = _save_session(store, current_session, history, agent)

        approval = ui.read_plan_approval()
        ui.console.print()

        if approval.lower() == "y":
            history.append(Message.user("Proceed with the approved plan."))
            event_queue = asyncio.Queue()
            worker = asyncio.create_task(agent.execute(history, event_queue))
            await ui.run_agent_stream(event_queue, input_queue, spinner_label="Executing")
            await worker
            current_session = _save_session(store, current_session, history, agent)
            return True, agent, current_session, history

        if approval.lower() in {"n", "no"}:
            ui.print_plan_rejected(plan_text)
            return False, agent, current_session, history

        history.append(Message.user(f"Revise the plan with this feedback: {approval}"))


def _save_session(
    store: SessionStore,
    current_session: SessionRecord,
    history: list[Message],
    agent: HarnessAgent,
) -> SessionRecord:
    return store.save_runtime(
        current_session,
        messages=history,
        todos=agent.todo_board().items(),
        audit_entries=agent.audit_log().entries(),
        token_usage=agent.token_usage_tracker().turns(),
    )


async def _resume_session(
    *,
    session_id: str,
    provider: OpenRouterProvider,
    input_queue: "asyncio.Queue[UserInputRequest]",
    store: SessionStore,
    router: SessionRouter,
    agent: HarnessAgent,
    current_route: SessionRoute,
    current_session: SessionRecord,
    history: list[Message],
    plan_mode: bool,
    ui: ConsoleUI,
) -> tuple[bool, HarnessAgent, SessionRoute, SessionRecord, list[Message], bool]:
    try:
        record = store.load(session_id)
    except FileNotFoundError:
        ui.print_unknown_session(session_id)
        return True, agent, current_route, current_session, history, plan_mode
    await agent.flush_memory_updates()
    ui.drain_notice_queue(agent.notice_queue())
    agent = build_agent(provider, cwd=record.cwd, input_queue=input_queue)
    history = store.restore_into_agent(agent, record)
    current_session = record
    current_route = router.bind(
        target_agent=current_route.target_agent,
        thread_key=current_route.thread_key,
        session_id=record.id,
    )
    plan_mode = False
    ui.print_resumed_session(record)
    ui.print_history_preview(history)
    return True, agent, current_route, current_session, history, plan_mode


async def _shutdown(agent: HarnessAgent, ui: ConsoleUI) -> None:
    await agent.flush_memory_updates()
    ui.drain_notice_queue(agent.notice_queue())
    ui.console.print()
