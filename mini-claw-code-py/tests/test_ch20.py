import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    AgentNotice,
    HarnessAgent,
    LEARNED_MEMORY_END,
    LEARNED_MEMORY_START,
    MemoryRegistry,
    Message,
    MockProvider,
    MockStreamProvider,
    StopReason,
    default_memory_sources,
    extract_learned_memory_lines,
    filter_messages_for_memory,
    latest_memory_exchange,
    load_memory_sources,
    merge_learned_memory_lines,
    render_memory_prompt_section,
    should_consider_memory_update,
)
from mini_claw_code_py.types import AssistantTurn, ToolCall


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


def test_ch20_filter_messages_for_memory_keeps_user_and_final_assistant_only() -> None:
    messages = [
        Message.system("System"),
        Message.user("Remember that I prefer concise answers."),
        Message.assistant(
            AssistantTurn(
                text=None,
                tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "a.py"})],
                stop_reason=StopReason.TOOL_USE,
            )
        ),
        Message.tool_result("c1", "file contents"),
        Message.assistant(
            AssistantTurn(
                text="I will keep answers concise.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]

    filtered = filter_messages_for_memory(messages)

    assert [message.kind for message in filtered] == ["user", "assistant"]
    assert should_consider_memory_update(filtered) is True


def test_ch20_latest_memory_exchange_avoids_reusing_old_memory_signal() -> None:
    messages = [
        Message.user("Please always include an emoji."),
        Message.assistant(
            AssistantTurn(
                text="I will include an emoji.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
        Message.user("Give me good news."),
        Message.assistant(
            AssistantTurn(
                text="Here is one happy update.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]

    snapshot = latest_memory_exchange(messages)

    assert [message.kind for message in snapshot] == ["user", "assistant"]
    assert snapshot[0].content == "Give me good news."
    assert should_consider_memory_update(snapshot) is False


def test_ch20_merge_learned_memory_lines_preserves_manual_memory_and_dedupes() -> None:
    text = "# Project memory\n- Use `uv run pytest`.\n"

    once = merge_learned_memory_lines(text, ["Include an emoji in every message."])
    twice = merge_learned_memory_lines(
        once,
        ["Include an emoji in every message; if none is specified, ask for placement."],
    )

    assert "# Project memory" in twice
    assert LEARNED_MEMORY_START in twice
    assert LEARNED_MEMORY_END in twice
    assert "Include an emoji in every message." not in twice
    assert extract_learned_memory_lines(twice) == [
        "Include an emoji in every message; if none is specified, ask for placement."
    ]


@pytest.mark.asyncio
async def test_ch20_memory_updates_append_managed_block_after_flush(tmp_path: Path) -> None:
    project_memory = tmp_path / ".agents" / "AGENTS.md"
    project_memory.parent.mkdir(parents=True)
    project_memory.write_text("# Project memory\n", encoding="utf-8")

    main_provider = MockStreamProvider(
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
    update_provider = MockProvider(
        deque(
            [
                AssistantTurn(
                    text='{"should_write": true, "lines": ["Prefer concise final answers."]}',
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = (
        HarnessAgent(main_provider)
        .enable_project_memory_file(project_memory)
        .enable_memory_updates(update_provider, debounce_seconds=0.0, target_scope="project")
    )

    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("For future tasks, prefer concise final answers.")]

    await agent.execute(messages, queue)
    await agent.flush_memory_updates()

    updated = project_memory.read_text(encoding="utf-8")
    assert "Prefer concise final answers." in updated
    assert LEARNED_MEMORY_START in updated
    background_notice = await asyncio.wait_for(agent.notice_queue().get(), timeout=1.0)
    assert background_notice.message == "Memory updated: project memory (+1 line)."

    notices: list[str] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentNotice):
            notices.append(event.message)

    assert any(message == "Memory update queued for project memory." for message in notices)


@pytest.mark.asyncio
async def test_ch20_memory_updates_skip_non_durable_conversation(tmp_path: Path) -> None:
    project_memory = tmp_path / ".agents" / "AGENTS.md"
    project_memory.parent.mkdir(parents=True)
    project_memory.write_text("# Project memory\n", encoding="utf-8")

    main_provider = MockStreamProvider(
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
        HarnessAgent(main_provider)
        .enable_project_memory_file(project_memory)
        .enable_memory_updates(MockProvider(deque()), debounce_seconds=0.0, target_scope="project")
    )

    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("What files changed today?")]

    await agent.execute(messages, queue)
    await agent.flush_memory_updates()

    updated = project_memory.read_text(encoding="utf-8")
    assert "mini-claw:memory-updater" not in updated


@pytest.mark.asyncio
async def test_ch20_harness_falls_back_when_model_returns_empty_text() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = HarnessAgent(provider)
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Hello")]

    result = await agent.execute(messages, queue)

    assert result == "I don't have a textual reply for that turn. Please try again."
