from __future__ import annotations

from dataclasses import dataclass

from .types import ToolCall


@dataclass(slots=True)
class AgentTextDelta:
    text: str


@dataclass(slots=True)
class AgentToolCall:
    name: str
    summary: str


@dataclass(slots=True)
class AgentDone:
    text: str


@dataclass(slots=True)
class AgentError:
    error: str


@dataclass(slots=True)
class AgentNotice:
    message: str


AgentEvent = AgentTextDelta | AgentToolCall | AgentDone | AgentError | AgentNotice


def tool_summary(call: ToolCall) -> str:
    detail = None
    if call.name == "write_todos" and isinstance(call.arguments, dict):
        items = call.arguments.get("items", call.arguments.get("todos"))
        if isinstance(items, list):
            return f"    [write_todos: {len(items)} item(s)]"
    if isinstance(call.arguments, dict):
        detail = (
            call.arguments.get("task")
            or call.arguments.get("description")
            or call.arguments.get("command")
            or call.arguments.get("path")
            or call.arguments.get("question")
        )
    if isinstance(detail, str):
        return f"    [{call.name}: {detail}]"
    return f"    [{call.name}]"
