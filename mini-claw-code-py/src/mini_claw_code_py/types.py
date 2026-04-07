from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence


JSONValue = Any


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "required": [],
        }
    )

    @classmethod
    def new(cls, name: str, description: str) -> "ToolDefinition":
        return cls(name=name, description=description)

    def param(
        self,
        name: str,
        type_: str,
        description: str,
        required: bool,
    ) -> "ToolDefinition":
        self.parameters["properties"][name] = {
            "type": type_,
            "description": description,
        }
        if required:
            self.parameters["required"].append(name)
        return self

    def param_raw(
        self,
        name: str,
        schema: dict[str, Any],
        required: bool,
    ) -> "ToolDefinition":
        self.parameters["properties"][name] = schema
        if required:
            self.parameters["required"].append(name)
        return self


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: JSONValue


class StopReason(str, Enum):
    STOP = "stop"
    TOOL_USE = "tool_use"


@dataclass(slots=True)
class AssistantTurn:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: StopReason


@dataclass(slots=True)
class Message:
    kind: str
    content: str | None = None
    turn: AssistantTurn | None = None
    tool_call_id: str | None = None

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls(kind="system", content=text)

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls(kind="user", content=text)

    @classmethod
    def assistant(cls, turn: AssistantTurn) -> "Message":
        return cls(kind="assistant", turn=turn)

    @classmethod
    def tool_result(cls, id: str, content: str) -> "Message":
        return cls(kind="tool_result", content=content, tool_call_id=id)


class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition:
        ...

    async def call(self, args: JSONValue) -> str:
        ...


class Provider(Protocol):
    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        ...


class ToolSet:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def with_tool(self, tool: Tool) -> "ToolSet":
        self.push(tool)
        return self

    def push(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def copy(self) -> "ToolSet":
        other = ToolSet()
        other._tools = dict(self._tools)
        return other
