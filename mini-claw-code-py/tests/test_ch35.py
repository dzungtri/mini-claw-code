import asyncio
from collections import deque
import json
from pathlib import Path
from typing import Sequence

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    Message,
    StopReason,
    SubagentProfileRegistry,
    ToolCall,
    ToolDefinition,
    default_subagent_config_paths,
    parse_subagent_config,
)
from mini_claw_code_py.streaming import StreamDone, TextDelta, ToolCallDelta, ToolCallStart
from mini_claw_code_py.types import AssistantTurn


def _write_subagents(path: Path, subagents: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"subagents": subagents}, indent=2), encoding="utf-8")
    return path


def _write_skill(root: Path, name: str, description: str, body: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )
    return skill_path


class HybridProvider:
    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self._responses = responses
        self.chat_calls: list[list[Message]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        self.chat_calls.append(list(messages))
        self.tool_definitions.append(list(tools))
        if not self._responses:
            raise RuntimeError("HybridProvider: no more responses")
        return self._responses.popleft()

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        queue: "asyncio.Queue[object]",
    ) -> AssistantTurn:
        turn = await self.chat(messages, tools)
        if turn.text:
            for char in turn.text:
                await queue.put(TextDelta(char))
        for index, call in enumerate(turn.tool_calls):
            await queue.put(ToolCallStart(index=index, id=call.id, name=call.name))
            await queue.put(ToolCallDelta(index=index, arguments=json.dumps(call.arguments)))
        await queue.put(StreamDone())
        return turn


def test_ch35_parse_subagent_config(tmp_path: Path) -> None:
    config_path = _write_subagents(
        tmp_path / ".subagents.json",
        {
            "researcher": {
                "description": "Use for research work.",
                "skills": ["research-notes"],
                "tools": ["read", "write"],
                "max_turns": 6,
            }
        },
    )

    [profile] = parse_subagent_config(config_path)

    assert profile.name == "researcher"
    assert profile.description == "Use for research work."
    assert profile.skills == ("research-notes",)
    assert profile.tools == ("read", "write")
    assert profile.max_turns == 6


def test_ch35_project_subagent_config_overrides_user_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "workspace" / "demo"
    project.mkdir(parents=True)

    _write_subagents(
        home / ".subagents.json",
        {
            "researcher": {
                "description": "User description",
                "tools": ["read"],
            }
        },
    )
    _write_subagents(
        project / ".subagents.json",
        {
            "researcher": {
                "description": "Project description",
                "tools": ["read", "bash"],
            }
        },
    )

    registry = SubagentProfileRegistry.discover(
        default_subagent_config_paths(cwd=project, home=home),
    )
    profile = registry.get("researcher")

    assert profile is not None
    assert profile.description == "Project description"
    assert profile.tools == ("read", "bash")


def test_ch35_registry_prompt_section_lists_available_profiles(tmp_path: Path) -> None:
    config_path = _write_subagents(
        tmp_path / ".subagents.json",
        {
            "researcher": {
                "description": "Research topics before writing.",
            },
            "editor": {
                "description": "Review and improve drafts.",
            },
        },
    )
    registry = SubagentProfileRegistry.discover([config_path])
    section = registry.prompt_section()

    assert "<configured_subagents>" in section
    assert "- editor: Review and improve drafts." in section
    assert "- researcher: Research topics before writing." in section


@pytest.mark.asyncio
async def test_ch35_harness_uses_profile_specific_tools_and_skills(tmp_path: Path) -> None:
    _write_subagents(
        tmp_path / ".subagents.json",
        {
            "researcher": {
                "description": "Use for focused research tasks.",
                "skills": ["research-notes"],
                "tools": ["read"],
                "max_turns": 4,
            }
        },
    )
    _write_skill(
        tmp_path / ".agents" / "skills",
        "research-notes",
        "Use this skill for research note taking.",
        "# Research Notes\nAlways save concise notes.",
    )
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="p1",
                            name="subagent",
                            arguments={
                                "task": "Research parser edge cases and summarize findings.",
                                "subagent_type": "researcher",
                            },
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Research complete.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text="Parent done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_default_skills(tmp_path)
        .enable_default_subagent_profiles(cwd=tmp_path, home=tmp_path / "home")
        .enable_subagents()
    )
    queue: asyncio.Queue[object] = asyncio.Queue()

    result = await agent.execute([Message.user("Use the researcher subagent.")], queue)

    assert result == "Parent done."
    assert "<configured_subagents>" in agent.execution_system_prompt
    child_messages = provider.chat_calls[1]
    assert child_messages[0].kind == "system"
    assert child_messages[0].content is not None
    assert "Type: researcher" in child_messages[0].content
    assert "Use for focused research tasks." in child_messages[0].content
    assert "<available_skills>" in child_messages[0].content
    assert "<name>research-notes</name>" in child_messages[0].content
    child_tool_names = [definition.name for definition in provider.tool_definitions[1]]
    assert child_tool_names == ["read"]


@pytest.mark.asyncio
async def test_ch35_unknown_subagent_type_returns_clear_error() -> None:
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="p1",
                            name="subagent",
                            arguments={"task": "Do research", "subagent_type": "missing"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Parent done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_subagents()
    queue: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Try a missing profile.")]

    result = await agent.execute(messages, queue)

    assert result == "Parent done."
    assert any(
        message.kind == "tool_result" and message.content == "error: unknown configured subagent type `missing`"
        for message in messages
    )


@pytest.mark.asyncio
async def test_ch35_unknown_profile_tool_returns_clear_error(tmp_path: Path) -> None:
    _write_subagents(
        tmp_path / ".subagents.json",
        {
            "researcher": {
                "description": "Use for research work.",
                "tools": ["read", "missing_tool"],
            }
        },
    )
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="p1",
                            name="subagent",
                            arguments={"task": "Research topic.", "subagent_type": "researcher"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(text="Parent done.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_default_subagent_profiles(cwd=tmp_path, home=tmp_path / "home")
        .enable_subagents()
    )
    messages = [Message.user("Use researcher.")]
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute(messages, queue)

    assert any(
        message.kind == "tool_result"
        and message.content == "error: configured subagent `researcher` references unknown tool `missing_tool`"
        for message in messages
    )


@pytest.mark.asyncio
async def test_ch35_missing_skill_registry_for_profile_skills_returns_clear_error(tmp_path: Path) -> None:
    _write_subagents(
        tmp_path / ".subagents.json",
        {
            "researcher": {
                "description": "Use for research work.",
                "skills": ["research-notes"],
            }
        },
    )
    provider = HybridProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="p1",
                            name="subagent",
                            arguments={"task": "Research topic.", "subagent_type": "researcher"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(text="Parent done.", tool_calls=[], stop_reason=StopReason.STOP),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_core_tools()
        .enable_default_subagent_profiles(cwd=tmp_path, home=tmp_path / "home")
        .enable_subagents()
    )
    messages = [Message.user("Use researcher.")]
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute(messages, queue)

    assert any(
        message.kind == "tool_result"
        and message.content == "error: configured subagent `researcher` requires skills, but no skill registry is active"
        for message in messages
    )
