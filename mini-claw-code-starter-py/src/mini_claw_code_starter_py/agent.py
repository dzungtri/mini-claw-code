from __future__ import annotations

from .types import Provider, ToolCall, ToolSet


def tool_summary(call: ToolCall) -> str:
    detail = None
    if isinstance(call.arguments, dict):
        detail = call.arguments.get("command") or call.arguments.get("path")
    if isinstance(detail, str):
        return f"    [{call.name}: {detail}]"
    return f"    [{call.name}]"


async def single_turn(provider: Provider, tools: ToolSet, prompt: str) -> str:
    """Chapter 3: one prompt, at most one round of tool calls."""

    raise NotImplementedError(
        "Collect tool definitions, call the provider, match on stop reason, "
        "execute tools if needed, and return the final text"
    )


class SimpleAgent:
    """Chapter 5: the full agent loop."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.tools = ToolSet()

    @classmethod
    def new(cls, provider: Provider) -> "SimpleAgent":
        raise NotImplementedError("Store the provider and initialize an empty ToolSet")

    def tool(self, tool: object) -> "SimpleAgent":
        raise NotImplementedError("Register the tool in self.tools and return self")

    async def run(self, prompt: str) -> str:
        raise NotImplementedError(
            "Loop until the provider returns StopReason.STOP, executing tool calls on each step"
        )

    async def chat(self, messages: list) -> str:
        raise NotImplementedError(
            "Same loop as run(), but operate on the caller-provided history list"
        )
