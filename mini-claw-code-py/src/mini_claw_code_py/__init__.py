from __future__ import annotations

import os
from pathlib import Path

from .agent import AgentDone, AgentError, AgentEvent, AgentTextDelta, AgentToolCall, SimpleAgent, single_turn
from .mock import MockProvider
from .planning import DEFAULT_PLAN_PROMPT_TEMPLATE, PlanAgent
from .providers import OpenRouterProvider
from .streaming import (
    MockStreamProvider,
    StreamAccumulator,
    StreamDone,
    StreamProvider,
    StreamingAgent,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    parse_sse_line,
)
from .subagent import SubagentTool
from .tools import (
    AskTool,
    BashTool,
    ChannelInputHandler,
    CliInputHandler,
    EditTool,
    InputHandler,
    MockInputHandler,
    ReadTool,
    UserInputRequest,
    WriteTool,
)
from .types import AssistantTurn, Message, Provider, StopReason, ToolCall, ToolDefinition, ToolSet

DEFAULT_SYSTEM_PROMPT_TEMPLATE = """You are a coding agent working in the user's local repository.

Your job is to help with software engineering tasks by inspecting the codebase, making
precise changes, using tools when helpful, and explaining results concisely.

General:
- Be direct, accurate, and brief.
- Inspect the code before making assumptions.
- Prefer `rg` or `rg --files` when searching text or files.
- Prefer small, correct changes over broad speculative edits.

Editing constraints:
- Default to ASCII when editing or creating files unless the file already uses non-ASCII.
- Add succinct code comments only when the code would otherwise be hard to follow.
- Follow the repository's existing patterns instead of introducing unnecessary style changes.
- Preserve user changes unless the user explicitly asks you to replace them.
- Never revert or overwrite unrelated changes you did not make.
- Avoid destructive actions such as forceful git resets or removing user work.

Task handling:
- State what you are about to do before substantial work.
- Surface risks, blockers, and missing information clearly.
- For simple requests that can be answered by inspecting the repo or running a command, do that directly.
- For reviews, focus on bugs, regressions, risks, and missing tests before summaries.

Responses:
- Keep answers concise and practical.
- After making changes, explain what changed, where, why, and what you verified.
- Reference file paths instead of dumping large files into the response.

Environment:
- Working directory: {{cwd}}
"""

SYSTEM_PROMPT_FILE_ENV = "MINI_CLAW_SYSTEM_PROMPT_FILE"
PLAN_PROMPT_FILE_ENV = "MINI_CLAW_PLAN_PROMPT_FILE"


def load_prompt_template(env_var: str, default_template: str) -> str:
    path = os.getenv(env_var, "").strip()
    if not path:
        return default_template
    return Path(path).read_text()


__all__ = [
    "AgentDone",
    "AgentError",
    "AgentEvent",
    "AgentTextDelta",
    "AgentToolCall",
    "AskTool",
    "AssistantTurn",
    "BashTool",
    "ChannelInputHandler",
    "CliInputHandler",
    "DEFAULT_PLAN_PROMPT_TEMPLATE",
    "DEFAULT_SYSTEM_PROMPT_TEMPLATE",
    "EditTool",
    "InputHandler",
    "Message",
    "MockInputHandler",
    "MockProvider",
    "MockStreamProvider",
    "OpenRouterProvider",
    "PLAN_PROMPT_FILE_ENV",
    "PlanAgent",
    "Provider",
    "ReadTool",
    "SYSTEM_PROMPT_FILE_ENV",
    "SimpleAgent",
    "StopReason",
    "StreamAccumulator",
    "StreamDone",
    "StreamProvider",
    "StreamingAgent",
    "SubagentTool",
    "TextDelta",
    "ToolCall",
    "ToolCallDelta",
    "ToolCallStart",
    "ToolDefinition",
    "ToolSet",
    "UserInputRequest",
    "WriteTool",
    "load_prompt_template",
    "parse_sse_line",
    "single_turn",
]
