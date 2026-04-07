import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    AgentNotice,
    HarnessAgent,
    Message,
    MockStreamProvider,
    StopReason,
    WorkspaceConfig,
    render_workspace_prompt_section,
    resolve_workspace_path,
    validate_bash_command,
)
from mini_claw_code_py.types import AssistantTurn, ToolCall


def test_ch21_resolve_workspace_aliases_and_relative_paths(tmp_path: Path) -> None:
    config = WorkspaceConfig(
        root=tmp_path / "repo",
        scratch=Path(".agent-work"),
        outputs=Path("outputs"),
    )

    assert resolve_workspace_path("notes/todo.md", config) == config.root / "notes" / "todo.md"
    assert resolve_workspace_path("workspace://src/app.py", config) == config.root / "src" / "app.py"
    assert resolve_workspace_path("scratch://plan.txt", config) == config.scratch / "plan.txt"
    assert resolve_workspace_path("outputs://report.md", config) == config.outputs / "report.md"


def test_ch21_resolve_workspace_path_rejects_out_of_bounds_path(tmp_path: Path) -> None:
    config = WorkspaceConfig(root=tmp_path / "repo")

    with pytest.raises(PermissionError):
        resolve_workspace_path(str(tmp_path / "outside.txt"), config)


def test_ch21_validate_bash_command_blocks_simple_destructive_patterns() -> None:
    validate_bash_command("pwd", allow_destructive=False)

    with pytest.raises(PermissionError):
        validate_bash_command("git reset --hard HEAD", allow_destructive=False)


def test_ch21_render_workspace_prompt_section_mentions_aliases(tmp_path: Path) -> None:
    config = WorkspaceConfig(
        root=tmp_path / "repo",
        scratch=Path(".agent-work"),
        outputs=Path("outputs"),
    )

    section = render_workspace_prompt_section(config)

    assert "<workspace>" in section
    assert "workspace://" in section
    assert "scratch://" in section
    assert "outputs://" in section
    assert "MINI_CLAW_WORKSPACE_ROOT" in section


@pytest.mark.asyncio
async def test_ch21_harness_workspace_tools_use_workspace_root_for_relative_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write",
                            arguments={"path": "notes/out.txt", "content": "hello workspace"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_workspace(
            repo,
            scratch=repo / ".agent-work",
            outputs=repo / "outputs",
        )
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Write the note")]

    result = await agent.execute(messages, queue)

    assert result == "Done."
    assert (repo / "notes" / "out.txt").read_text(encoding="utf-8") == "hello workspace"

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)
    assert any(message.startswith("Workspace ready:") for message in notices)


@pytest.mark.asyncio
async def test_ch21_harness_workspace_bash_uses_root_as_cwd(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="bash",
                            arguments={"command": "pwd"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().workspace(repo)
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Show the working directory")]

    await agent.execute(messages, queue)

    tool_results = [message.content for message in messages if message.kind == "tool_result"]
    assert any(str(repo) in (content or "") for content in tool_results)


@pytest.mark.asyncio
async def test_ch21_harness_workspace_blocks_destructive_bash_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="bash",
                            arguments={"command": "git reset --hard HEAD"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().workspace(repo)
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Run reset")]

    await agent.execute(messages, queue)

    tool_results = [message.content for message in messages if message.kind == "tool_result"]
    assert any("blocked potentially destructive bash command" in (content or "") for content in tool_results)
