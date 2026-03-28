import asyncio
import json
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    CONFIG_PATH_ENV,
    CONTROL_PROFILE_ENV,
    HarnessAgent,
    Message,
    MockInputHandler,
    MockStreamProvider,
    StopReason,
    apply_harness_config,
    default_harness_config_paths,
    load_harness_config,
)
from mini_claw_code_py.events import AgentNotice
from mini_claw_code_py.types import AssistantTurn


def test_ch31_default_harness_config_paths_follow_user_project_then_explicit_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    explicit = tmp_path / "demo" / "alt.json"
    home.mkdir()
    project.mkdir()
    explicit.parent.mkdir(parents=True)

    (home / ".mini-claw.json").write_text("{}\n", encoding="utf-8")
    (project / ".mini-claw.json").write_text("{}\n", encoding="utf-8")
    explicit.write_text("{}\n", encoding="utf-8")

    paths = default_harness_config_paths(
        cwd=project,
        home=home,
        env={CONFIG_PATH_ENV: str(explicit)},
    )

    assert paths == [
        (home / ".mini-claw.json").resolve(),
        (project / ".mini-claw.json").resolve(),
        explicit.resolve(),
    ]


def test_ch31_load_harness_config_merges_user_and_project_files_with_relative_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    (home / ".mini-claw.json").write_text(
        json.dumps(
            {
                "enable_mcp": False,
                "workspace": {"outputs": "home-outputs"},
                "control_plane_profile": "safe",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (project / ".mini-claw.json").write_text(
        json.dumps(
            {
                "workspace": {"scratch": "tmp/scratch", "outputs": "build/outputs"},
                "subagents": {"max_parallel": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_harness_config(cwd=project, home=home, env={})

    assert config.enable_mcp is False
    assert config.control_plane_profile == "safe"
    assert config.workspace.outputs == (project / "build" / "outputs").resolve()
    assert config.workspace.scratch == (project / "tmp" / "scratch").resolve()
    assert config.subagent_max_parallel == 1


def test_ch31_explicit_env_config_file_overrides_discovered_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    explicit = tmp_path / "configs" / "ci.json"
    home.mkdir()
    project.mkdir()
    explicit.parent.mkdir(parents=True)

    (project / ".mini-claw.json").write_text(
        json.dumps({"enable_skills": True, "control_plane_profile": "balanced"}) + "\n",
        encoding="utf-8",
    )
    explicit.write_text(
        json.dumps({"enable_skills": False, "control_plane_profile": "trusted"}) + "\n",
        encoding="utf-8",
    )

    config = load_harness_config(
        cwd=project,
        home=home,
        env={CONFIG_PATH_ENV: str(explicit)},
    )

    assert config.enable_skills is False
    assert config.control_plane_profile == "trusted"


def test_ch31_control_profile_env_override_wins_last(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    (project / ".mini-claw.json").write_text(
        json.dumps({"control_plane_profile": "trusted"}) + "\n",
        encoding="utf-8",
    )

    config = load_harness_config(
        cwd=project,
        home=home,
        env={CONTROL_PROFILE_ENV: "safe"},
    )

    assert config.control_plane_profile == "safe"


def test_ch31_missing_explicit_env_config_file_raises_clear_error(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    missing = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match=CONFIG_PATH_ENV):
        load_harness_config(
            cwd=project,
            home=home,
            env={CONFIG_PATH_ENV: str(missing)},
        )


@pytest.mark.asyncio
async def test_ch31_loaded_config_applies_runtime_shape_to_harness_agent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (project / ".mini-claw.json").write_text(
        json.dumps(
            {
                "enable_mcp": False,
                "enable_skills": False,
                "enable_subagents": False,
                "enable_tool_universe": False,
                "control_plane_profile": "safe",
                "workspace": {"outputs": "dist"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_harness_config(cwd=project, home=home, env={})
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Configured.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = HarnessAgent(provider)
    apply_harness_config(
        agent,
        config,
        handler=MockInputHandler(deque()),
    )

    queue: asyncio.Queue[object] = asyncio.Queue()
    result = await agent.execute([Message.user("Hello")], queue)

    assert result == "Configured."

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)

    assert any("profile=safe" in notice for notice in notices)
    assert any("outputs=" + str((project / "dist").resolve()) in notice for notice in notices)
    assert not any(notice.startswith("MCP connected:") for notice in notices)
    assert not any(notice.startswith("Subagent capability available:") for notice in notices)
