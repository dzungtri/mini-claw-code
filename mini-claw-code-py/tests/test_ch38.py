import asyncio
import json
from collections import deque
from pathlib import Path

from mini_claw_code_py import (
    AGENT_REGISTRY_FILE_NAME,
    AgentNotice,
    HostedAgentFactory,
    HostedAgentRegistry,
    Message,
    MockStreamProvider,
    StopReason,
    default_agent_registry_paths,
    default_superagent_definition,
    parse_agent_registry,
)
from mini_claw_code_py.tools import UserInputRequest
from mini_claw_code_py.types import AssistantTurn


def test_ch38_default_agent_registry_paths_follow_user_then_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / AGENT_REGISTRY_FILE_NAME).write_text('{"agents": {}}\n', encoding="utf-8")
    (project / AGENT_REGISTRY_FILE_NAME).write_text('{"agents": {}}\n', encoding="utf-8")

    paths = default_agent_registry_paths(cwd=project, home=home)

    assert paths == [
        (home / AGENT_REGISTRY_FILE_NAME).resolve(),
        (project / AGENT_REGISTRY_FILE_NAME).resolve(),
    ]


def test_ch38_registry_discovers_built_in_superagent_when_no_files_exist(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    registry = HostedAgentRegistry.discover_default(cwd=project, home=home)
    definition = registry.require("superagent")

    assert definition.name == "superagent"
    assert definition.workspace_root == project.resolve()
    assert definition.default_channels == ("cli",)


def test_ch38_parse_agent_registry_resolves_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config_path = root / AGENT_REGISTRY_FILE_NAME
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "reviewer": {
                        "description": "Review repository changes.",
                        "workspace_root": "packages/reviewer",
                        "config_path": "configs/reviewer.json",
                        "default_channels": ["bus"],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_agent_registry(config_path)
    reviewer = parsed["reviewer"]

    assert reviewer.workspace_root == (root / "packages" / "reviewer").resolve()
    assert reviewer.config_path == (root / "configs" / "reviewer.json").resolve()
    assert reviewer.default_channels == ("bus",)


def test_ch38_registry_merges_user_and_project_agent_fields(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / AGENT_REGISTRY_FILE_NAME).write_text(
        json.dumps(
            {
                "agents": {
                    "reviewer": {
                        "description": "General review agent",
                        "workspace_root": "shared/reviewer",
                        "default_channels": ["bus", "cli"],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (project / AGENT_REGISTRY_FILE_NAME).write_text(
        json.dumps(
            {
                "agents": {
                    "reviewer": {
                        "description": "Project-specific reviewer",
                        "config_path": "configs/reviewer.json",
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry = HostedAgentRegistry.discover_default(cwd=project, home=home)
    reviewer = registry.require("reviewer")

    assert reviewer.description == "Project-specific reviewer"
    assert reviewer.workspace_root == (home / "shared" / "reviewer").resolve()
    assert reviewer.default_channels == ("bus", "cli")
    assert reviewer.config_path == (project / "configs" / "reviewer.json").resolve()


async def _execute_with_definition(tmp_path: Path) -> list[str]:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    config_dir = workspace / "configs"
    config_dir.mkdir()
    agent_config = config_dir / "reviewer.json"
    agent_config.write_text(
        json.dumps(
            {
                "enable_mcp": False,
                "enable_skills": False,
                "enable_subagents": False,
                "enable_tool_universe": False,
                "workspace": {"outputs": "agent-dist"},
                "control_plane_profile": "safe",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry_path = workspace / AGENT_REGISTRY_FILE_NAME
    registry_path.write_text(
        json.dumps(
            {
                "agents": {
                    "reviewer": {
                        "description": "Dedicated review agent.",
                        "workspace_root": ".",
                        "config_path": "configs/reviewer.json",
                        "default_channels": ["cli"],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry = HostedAgentRegistry.discover_default(cwd=workspace, home=tmp_path / "home")
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Ready.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    agent = HostedAgentFactory(
        provider=provider,  # type: ignore[arg-type]
        home=home,
        input_queue=input_queue,
    ).build(registry.require("reviewer"))

    queue: asyncio.Queue[object] = asyncio.Queue()
    result = await agent.execute([Message.user("Hello")], queue)

    assert result == "Ready."

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    return notices


def test_ch38_hosted_agent_factory_builds_harness_from_agent_config_path(tmp_path: Path) -> None:
    notices = asyncio.run(_execute_with_definition(tmp_path))

    assert any("profile=safe" in notice for notice in notices)
    assert any(
        "outputs=" + str((tmp_path / "workspace" / "configs" / "agent-dist").resolve()) in notice
        for notice in notices
    )
    assert not any(notice.startswith("MCP connected:") for notice in notices)
    assert not any(notice.startswith("Subagent capability available:") for notice in notices)


def test_ch38_default_superagent_definition_uses_current_workspace() -> None:
    definition = default_superagent_definition(Path("/tmp/demo"))

    assert definition.name == "superagent"
    assert definition.workspace_root == Path("/tmp/demo").resolve()
    assert definition.default_channels == ("cli",)
