from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from mini_claw_code_py import (
    ChannelRegistry,
    HarnessAgent,
    HostedAgentFactory,
    HostedAgentRegistry,
    Message,
    MessageEnvelope,
    OpenRouterProvider,
    GoalStore,
    RunStore,
    SessionWorkStore,
    SkillHubManager,
    SessionRoute,
    SessionRecord,
    SessionStore,
    SessionRouter,
    TaskStore,
    TeamRegistry,
    TurnRunner,
    UserInputRequest,
    default_os_state_root,
    default_route_store,
)
from mini_claw_code_py.mcp import MCPServer
from mini_claw_code_py.os.agent_registry import HostedAgentDefinition
from mini_claw_code_py.os.channels import ChannelDefinition
from mini_claw_code_py.os.management import add_channel, add_hosted_agent, add_mcp_server, add_team
from mini_claw_code_py.os.work import TeamDefinition

from .console import ConsoleUI


CLI_CHANNEL_NAME = "cli"
CLI_THREAD_SUFFIX = "local"


def resolve_cli_route(
    *,
    cwd: Path,
    home: Path,
    teams: TeamRegistry | None = None,
    channels: ChannelRegistry | None = None,
) -> tuple[ChannelRegistry, str, str]:
    registry = channels or ChannelRegistry.discover_default(cwd=cwd, home=home)
    channel = registry.require(CLI_CHANNEL_NAME)
    target_agent = channel.resolve_target_agent(teams)
    thread_key = channel.resolve_thread_key(CLI_THREAD_SUFFIX)
    return registry, target_agent, thread_key


def build_agent(
    provider: OpenRouterProvider,
    *,
    cwd: Path,
    input_queue: "asyncio.Queue[UserInputRequest]",
    home: Path | None = None,
    target_agent: str | None = None,
) -> HarnessAgent:
    resolved_home = Path.home() if home is None else Path(home)
    registry = HostedAgentRegistry.discover_default(cwd=cwd, home=resolved_home)
    definition = registry.require(target_agent or "superagent")
    return HostedAgentFactory(
        provider=provider,
        home=resolved_home,
        input_queue=input_queue,
    ).build(definition)


async def run_cli(*, cwd: Path | None = None) -> None:
    provider = OpenRouterProvider.from_env()
    workspace = (cwd or Path.cwd()).resolve()
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    store = SessionStore(workspace / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(workspace), store)
    runs = RunStore(default_os_state_root(workspace))
    teams = TeamRegistry.discover_default(cwd=workspace, home=Path.home())
    channels, cli_target_agent, cli_thread_key = resolve_cli_route(cwd=workspace, home=Path.home(), teams=teams)
    goals = GoalStore(default_os_state_root(workspace))
    tasks = TaskStore(default_os_state_root(workspace))
    session_work = SessionWorkStore(default_os_state_root(workspace))
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
        teams=teams,
        goals=goals,
        tasks=tasks,
        session_work=session_work,
    )

    agent = build_agent(provider, cwd=workspace, input_queue=input_queue, target_agent=cli_target_agent)
    current_route, current_session = router.resolve_or_create(
        target_agent=cli_target_agent,
        thread_key=cli_thread_key,
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
                goals=goals,
                tasks=tasks,
                session_work=session_work,
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
    goals: GoalStore | None = None,
    tasks: TaskStore | None = None,
    session_work: SessionWorkStore | None = None,
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
    if prompt.startswith("/mcp add"):
        try:
            path, server = _add_mcp_command(prompt, cwd=workspace)
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        await agent.flush_memory_updates()
        ui.drain_notice_queue(agent.notice_queue())
        agent = build_agent(
            provider,
            cwd=workspace,
            input_queue=input_queue,
            target_agent=current_route.target_agent,
        )
        history = store.restore_into_agent(agent, current_session)
        ui.print_rendered_text(
            "MCP Added",
            "\n".join(
                [
                    f"name={server.name}",
                    f"transport={server.transport}",
                    f"config={path}",
                ]
            ),
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/subagents":
        ui.print_subagents(agent)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/agents":
        ui.print_agents(
            HostedAgentRegistry.discover_default(cwd=workspace, home=Path.home()),
            current_agent=current_route.target_agent,
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/agent add"):
        try:
            path, definition = _add_agent_command(prompt, cwd=workspace)
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_rendered_text(
            "Agent Added",
            "\n".join(
                [
                    f"name={definition.name}",
                    f"workspace={definition.workspace_root}",
                    f"channels={', '.join(definition.default_channels)}",
                    f"config={path}",
                ]
            ),
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/channels":
        ui.print_channels(ChannelRegistry.discover_default(cwd=workspace, home=Path.home()))
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/channel add"):
        try:
            path, definition = _add_channel_command(prompt, cwd=workspace)
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_rendered_text(
            "Channel Added",
            "\n".join(
                [
                    f"name={definition.name}",
                    f"target={definition.default_target_agent or f'team:{definition.default_team}'}",
                    f"thread_prefix={definition.thread_prefix}",
                    f"config={path}",
                ]
            ),
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/teams":
        ui.print_teams(TeamRegistry.discover_default(cwd=workspace, home=Path.home()))
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/team add"):
        try:
            path, definition = _add_team_command(prompt, cwd=workspace)
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_rendered_text(
            "Team Added",
            "\n".join(
                [
                    f"name={definition.name}",
                    f"lead={definition.lead_agent}",
                    f"members={', '.join(definition.member_agents)}",
                    f"workspace={definition.workspace_root or workspace}",
                    f"config={path}",
                ]
            ),
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/skills":
        ui.print_rendered_text("Skills", _skill_hub_manager(workspace).render())
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/skill search"):
        query = prompt[len("/skill search") :].strip()
        if not query:
            ui.print_usage("/skill search <query>")
            return True, agent, current_route, current_session, history, plan_mode
        try:
            result = _skill_hub_manager(workspace).search(query)
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_rendered_text("Skill Search", result.stdout or "(no output)")
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/skill install-user"):
        try:
            install = _skill_hub_manager(workspace).install_user_skill(
                **_parse_skill_install_args(prompt, slug_index=2)
            )
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_rendered_text(
            "Skill Install",
            "\n".join(
                [
                    f"Installed {install.slug}",
                    f"scope={install.scope}",
                    f"install_root={install.install_root}",
                    f"version={install.version or 'latest'}",
                ]
            ),
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/skill install"):
        install_args = _parse_skill_install_args(prompt, slug_index=2)
        install_user = bool(install_args.pop("install_user", False))
        try:
            install = (
                _skill_hub_manager(workspace).install_user_skill(**install_args)
                if install_user
                else _skill_hub_manager(workspace).install_project_skill(**install_args)
            )
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_rendered_text(
            "Skill Install",
            "\n".join(
                [
                    f"Installed {install.slug}",
                    f"scope={install.scope}",
                    f"install_root={install.install_root}",
                    f"version={install.version or 'latest'}",
                ]
            ),
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/work":
        ui.print_work_status(
            session_id=current_session.id,
            binding=None if session_work is None else session_work.get(current_session.id),
            goals=goals,
            tasks=tasks,
        )
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/goals":
        if goals is None:
            ui.print_usage("Goal store is not available.")
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_goals(goals)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/tasks":
        if tasks is None:
            ui.print_usage("Task store is not available.")
            return True, agent, current_route, current_session, history, plan_mode
        ui.print_tasks(tasks)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/routes":
        ui.print_routes(router.routes)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt == "/runs":
        ui.print_runs(runs)
        return True, agent, current_route, current_session, history, plan_mode
    if prompt.startswith("/use "):
        try:
            target_agent, thread_key, summary = _resolve_route_command(prompt, cwd=workspace)
        except Exception as exc:
            ui.print_usage(str(exc))
            return True, agent, current_route, current_session, history, plan_mode
        return await _switch_route(
            provider=provider,
            workspace=workspace,
            input_queue=input_queue,
            store=store,
            router=router,
            agent=agent,
            current_route=current_route,
            current_session=current_session,
            history=history,
            plan_mode=plan_mode,
            ui=ui,
            target_agent=target_agent,
            thread_key=thread_key,
            reason=summary,
        )
    if prompt == "/session":
        ui.print_session_status(
            current_session,
            route=current_route,
            binding=None if session_work is None else session_work.get(current_session.id),
        )
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
        agent = build_agent(
            provider,
            cwd=workspace,
            input_queue=input_queue,
            target_agent=current_route.target_agent,
        )
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
    agent = build_agent(
        provider,
        cwd=record.cwd,
        input_queue=input_queue,
        target_agent=current_route.target_agent,
    )
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


def _skill_hub_manager(workspace: Path) -> SkillHubManager:
    return SkillHubManager(
        cwd=workspace,
        home=Path.home(),
        root=default_os_state_root(workspace),
    )


def _parse_skill_install_args(prompt: str, *, slug_index: int) -> dict[str, object]:
    parts = prompt.split()
    if len(parts) <= slug_index:
        raise ValueError("/skill install <slug> [--version <v>] [--force]")
    slug = parts[slug_index].strip()
    if not slug:
        raise ValueError("skill slug cannot be empty")
    version: str | None = None
    force = False
    install_user = False
    index = slug_index + 1
    while index < len(parts):
        part = parts[index]
        if part == "--version":
            if index + 1 >= len(parts):
                raise ValueError("--version requires a value")
            version = parts[index + 1].strip()
            index += 2
            continue
        if part == "--force":
            force = True
            index += 1
            continue
        if part == "--user":
            install_user = True
            index += 1
            continue
        raise ValueError(f"unsupported skill install option: {part}")
    return {
        "slug": slug,
        "version": version,
        "force": force,
        "install_user": install_user,
    }


def _add_agent_command(prompt: str, *, cwd: Path) -> tuple[Path, HostedAgentDefinition]:
    parts = shlex.split(prompt)
    if len(parts) < 4:
        raise ValueError('/agent add <name> --workspace <path> --description "..." [--channel <name>] [--config <path>] [--remote <url>]')
    name = parts[2].strip()
    description = ""
    workspace_root: Path | None = None
    config_path: Path | None = None
    remote_endpoint: str | None = None
    default_channels: list[str] = []
    index = 3
    while index < len(parts):
        part = parts[index]
        if part == "--workspace":
            workspace_root = (cwd / parts[index + 1]).resolve()
            index += 2
            continue
        if part == "--description":
            description = parts[index + 1]
            index += 2
            continue
        if part == "--channel":
            default_channels.append(parts[index + 1].strip())
            index += 2
            continue
        if part == "--config":
            config_path = (cwd / parts[index + 1]).resolve()
            index += 2
            continue
        if part == "--remote":
            remote_endpoint = parts[index + 1].strip()
            index += 2
            continue
        raise ValueError(f"unsupported /agent add option: {part}")
    if workspace_root is None:
        raise ValueError("agent workspace is required")
    definition = HostedAgentDefinition(
        name=name,
        description=description or f"Hosted agent {name}",
        workspace_root=workspace_root,
        default_channels=tuple(default_channels or ("cli",)),
        config_path=config_path,
        remote_endpoint=remote_endpoint,
    )
    known_channels = ChannelRegistry.discover_default(cwd=cwd, home=Path.home())
    for channel_name in definition.default_channels:
        known_channels.require(channel_name)
    path = add_hosted_agent(cwd=cwd, definition=definition)
    return path, definition


def _add_team_command(prompt: str, *, cwd: Path) -> tuple[Path, TeamDefinition]:
    parts = shlex.split(prompt)
    if len(parts) < 4:
        raise ValueError('/team add <name> --lead <agent> [--member <name>] [--workspace <path>] [--description "..."]')
    name = parts[2].strip()
    lead_agent: str | None = None
    description = ""
    members: list[str] = []
    workspace_root: Path | None = None
    index = 3
    while index < len(parts):
        part = parts[index]
        if part == "--lead":
            lead_agent = parts[index + 1].strip()
            index += 2
            continue
        if part == "--member":
            members.append(parts[index + 1].strip())
            index += 2
            continue
        if part == "--workspace":
            workspace_root = (cwd / parts[index + 1]).resolve()
            index += 2
            continue
        if part == "--description":
            description = parts[index + 1]
            index += 2
            continue
        raise ValueError(f"unsupported /team add option: {part}")
    if lead_agent is None:
        raise ValueError("team lead is required")
    HostedAgentRegistry.discover_default(cwd=cwd, home=Path.home()).require(lead_agent)
    for member in members:
        HostedAgentRegistry.discover_default(cwd=cwd, home=Path.home()).require(member)
    definition = TeamDefinition(
        name=name,
        description=description or f"Team {name}",
        lead_agent=lead_agent,
        member_agents=tuple(members or (lead_agent,)),
        workspace_root=workspace_root,
    )
    path = add_team(cwd=cwd, definition=definition)
    return path, definition


def _add_channel_command(prompt: str, *, cwd: Path) -> tuple[Path, ChannelDefinition]:
    parts = shlex.split(prompt)
    if len(parts) < 4:
        raise ValueError('/channel add <name> (--agent <name> | --team <name>) [--prefix <prefix>] [--description "..."]')
    name = parts[2].strip()
    description = ""
    default_target_agent: str | None = None
    default_team: str | None = None
    thread_prefix: str | None = None
    index = 3
    while index < len(parts):
        part = parts[index]
        if part == "--agent":
            default_target_agent = parts[index + 1].strip()
            index += 2
            continue
        if part == "--team":
            default_team = parts[index + 1].strip()
            index += 2
            continue
        if part == "--prefix":
            thread_prefix = parts[index + 1].strip()
            index += 2
            continue
        if part == "--description":
            description = parts[index + 1]
            index += 2
            continue
        raise ValueError(f"unsupported /channel add option: {part}")
    if not default_target_agent and not default_team:
        raise ValueError("channel must target an agent or a team")
    if default_target_agent:
        HostedAgentRegistry.discover_default(cwd=cwd, home=Path.home()).require(default_target_agent)
    if default_team:
        TeamRegistry.discover_default(cwd=cwd, home=Path.home()).require(default_team)
    definition = ChannelDefinition(
        name=name,
        description=description or f"Channel {name}",
        default_target_agent=default_target_agent,
        default_team=default_team,
        thread_prefix=thread_prefix,
    )
    path = add_channel(cwd=cwd, definition=definition)
    return path, definition


def _add_mcp_command(prompt: str, *, cwd: Path) -> tuple[Path, MCPServer]:
    parts = shlex.split(prompt)
    if len(parts) < 5:
        raise ValueError("/mcp add <stdio|http|sse> <name> <command|url> [args...]")
    transport = parts[2].strip()
    name = parts[3].strip()
    if transport == "stdio":
        command = parts[4].strip()
        args = parts[5:]
        server = MCPServer(
            name=name,
            config_path=(cwd / ".mcp.json").resolve(),
            transport="stdio",
            command=command,
            args=args,
        )
    elif transport in {"http", "sse"}:
        url = parts[4].strip()
        server = MCPServer(
            name=name,
            config_path=(cwd / ".mcp.json").resolve(),
            transport=transport,
            url=url,
        )
    else:
        raise ValueError(f"unsupported MCP transport: {transport}")
    path = add_mcp_server(cwd=cwd, server=server)
    return path, server


def _resolve_route_command(prompt: str, *, cwd: Path) -> tuple[str, str, str]:
    parts = shlex.split(prompt)
    if len(parts) < 3:
        raise ValueError("/use <agent|team|channel> <name>")
    kind = parts[1].strip()
    name = parts[2].strip()
    teams = TeamRegistry.discover_default(cwd=cwd, home=Path.home())
    channels = ChannelRegistry.discover_default(cwd=cwd, home=Path.home())
    if kind == "agent":
        return name, "cli:local", f"agent={name} thread=cli:local"
    if kind == "team":
        team = teams.require(name)
        return team.lead_agent, "cli:local", f"team={team.name} lead={team.lead_agent} thread=cli:local"
    if kind == "channel":
        channel = channels.require(name)
        target_agent = channel.resolve_target_agent(teams)
        thread_key = channel.resolve_thread_key(CLI_THREAD_SUFFIX)
        return target_agent, thread_key, f"channel={channel.name} agent={target_agent} thread={thread_key}"
    raise ValueError(f"unsupported route target: {kind}")


async def _switch_route(
    *,
    provider: OpenRouterProvider,
    workspace: Path,
    input_queue: "asyncio.Queue[UserInputRequest]",
    store: SessionStore,
    router: SessionRouter,
    agent: HarnessAgent,
    current_route: SessionRoute,
    current_session: SessionRecord,
    history: list[Message],
    plan_mode: bool,
    ui: ConsoleUI,
    target_agent: str,
    thread_key: str,
    reason: str,
) -> tuple[bool, HarnessAgent, SessionRoute, SessionRecord, list[Message], bool]:
    current_session = _save_session(store, current_session, history, agent)
    await agent.flush_memory_updates()
    ui.drain_notice_queue(agent.notice_queue())
    registry = HostedAgentRegistry.discover_default(cwd=workspace, home=Path.home())
    definition = registry.require(target_agent)
    agent = build_agent(
        provider,
        cwd=workspace,
        input_queue=input_queue,
        target_agent=target_agent,
    )
    current_route, current_session = router.resolve_or_create(
        target_agent=target_agent,
        thread_key=thread_key,
        cwd=definition.workspace_root,
    )
    history = store.restore_into_agent(agent, current_session)
    plan_mode = False
    ui.print_rendered_text(
        "Route Updated",
        "\n".join(
            [
                reason,
                f"session={current_session.id}",
            ]
        ),
    )
    if history:
        ui.print_history_preview(history)
    return True, agent, current_route, current_session, history, plan_mode
