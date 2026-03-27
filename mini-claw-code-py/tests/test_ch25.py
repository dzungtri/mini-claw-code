import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    Message,
    MockInputHandler,
    MockStreamProvider,
    StopReason,
    ToolCall,
    apply_harness_config,
    default_harness_config,
    tool_summary,
)
from mini_claw_code_py.events import AgentNotice
from mini_claw_code_py.types import AssistantTurn


def test_ch25_default_harness_config_uses_flat_runtime_defaults(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    config = default_harness_config(cwd=tmp_path, home=home)

    assert config.cwd == tmp_path.resolve()
    assert config.home == home.resolve()
    assert config.workspace.root == tmp_path.resolve()
    assert config.workspace.scratch == (tmp_path / ".agent-work").resolve()
    assert config.workspace.outputs == (tmp_path / "outputs").resolve()
    assert config.enable_context_durability is True
    assert config.enable_subagents is True
    assert config.enable_control_plane is True
    assert config.control_plane_profile == "balanced"
    assert config.enable_token_usage_tracing is True


def test_ch25_tool_summary_lives_in_runtime_events_module() -> None:
    summary = tool_summary(
        ToolCall(
            id="t1",
            name="write_todos",
            arguments={"items": ["one", "two", "three"]},
        )
    )

    assert summary == "    [write_todos: 3 item(s)]"


@pytest.mark.asyncio
async def test_ch25_apply_harness_config_boots_expected_runtime_features(tmp_path: Path) -> None:
    home = tmp_path / "home"
    memory_file = home / ".agents" / "AGENTS.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("# User Memory\n\nPrefer concise answers.\n", encoding="utf-8")

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
    agent = HarnessAgent(provider)
    config = default_harness_config(cwd=tmp_path, home=home)
    apply_harness_config(
        agent,
        config,
        handler=MockInputHandler(deque()),
    )

    queue: asyncio.Queue[object] = asyncio.Queue()
    result = await agent.execute([Message.user("Say hello")], queue)

    assert result == "Ready."

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)

    assert any(message.startswith("Memory loaded:") for message in notices)
    assert any(message.startswith("Workspace ready:") for message in notices)
    assert any(message.startswith("Tool universe ready:") for message in notices)
    assert any(message.startswith("Control plane active:") and "profile=balanced" in message for message in notices)
    assert not any(message.startswith("Subagent capability available:") for message in notices)
