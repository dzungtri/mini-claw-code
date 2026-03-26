import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    AgentNotice,
    HarnessAgent,
    MemoryRegistry,
    Message,
    MockStreamProvider,
    StopReason,
    default_memory_sources,
    load_memory_sources,
    render_memory_prompt_section,
)
from mini_claw_code_py.types import AssistantTurn


def test_ch20_default_memory_sources_load_project_then_user(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    project_memory = repo / ".agents" / "AGENTS.md"
    project_memory.parent.mkdir(parents=True)
    project_memory.write_text("- Use `uv run pytest`.\n", encoding="utf-8")

    home = tmp_path / "home"
    user_memory = home / ".agents" / "AGENTS.md"
    user_memory.parent.mkdir(parents=True)
    user_memory.write_text("- Prefer concise explanations.\n", encoding="utf-8")

    sources = default_memory_sources(cwd=nested, home=home)

    assert [(source.scope, source.path) for source in sources] == [
        ("project", project_memory),
        ("user", user_memory),
    ]

    documents = load_memory_sources(sources)

    assert [document.scope for document in documents] == ["project", "user"]
    section = render_memory_prompt_section(documents)
    assert "<agent_memory>" in section
    assert 'scope="project"' in section
    assert 'scope="user"' in section
    assert str(project_memory) in section
    assert str(user_memory) in section


@pytest.mark.asyncio
async def test_ch20_harness_loads_memory_at_runtime_from_latest_file_contents(tmp_path: Path) -> None:
    project_memory = tmp_path / ".agents" / "AGENTS.md"
    project_memory.parent.mkdir(parents=True)
    project_memory.write_text("- Old memory.\n", encoding="utf-8")

    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Used fresh memory.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = HarnessAgent(provider).enable_project_memory_file(project_memory)
    project_memory.write_text("- Fresh memory.\n", encoding="utf-8")

    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("What guidance applies here?")]

    result = await agent.execute(messages, queue)

    assert result == "Used fresh memory."
    assert messages[0].kind == "system"
    assert messages[0].content is not None
    assert "- Fresh memory." in messages[0].content
    assert "- Old memory." not in messages[0].content


@pytest.mark.asyncio
async def test_ch20_harness_emits_memory_notice_and_preserves_project_then_user_order(
    tmp_path: Path,
) -> None:
    project_memory = tmp_path / "repo" / ".agents" / "AGENTS.md"
    project_memory.parent.mkdir(parents=True)
    project_memory.write_text("- Project memory.\n", encoding="utf-8")

    user_memory = tmp_path / "home" / ".agents" / "AGENTS.md"
    user_memory.parent.mkdir(parents=True)
    user_memory.write_text("- User memory.\n", encoding="utf-8")

    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_project_memory_file(project_memory)
        .enable_user_memory_file(user_memory)
    )

    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Continue")]
    await agent.execute(messages, queue)

    assert messages[0].content is not None
    prompt = messages[0].content
    assert prompt.index(str(project_memory)) < prompt.index(str(user_memory))

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)

    assert any(message.startswith("Memory loaded:") for message in notices)


def test_ch20_memory_registry_prompt_section_is_empty_when_no_files_exist(tmp_path: Path) -> None:
    registry = MemoryRegistry.discover_default(cwd=tmp_path / "repo", home=tmp_path / "home")

    assert registry.prompt_section() == ""
    assert registry.status_summary() == ""
