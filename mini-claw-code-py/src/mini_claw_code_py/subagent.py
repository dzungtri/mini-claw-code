from __future__ import annotations

from typing import Any, Callable

from .types import Message, Provider, StopReason, ToolDefinition, ToolSet


class SubagentTool:
    def __init__(self, provider: Provider, tools_factory: Callable[[], ToolSet]) -> None:
        self.provider = provider
        self.tools_factory = tools_factory
        self._system_prompt: str | None = None
        self.max_turns_value = 10
        self._definition = ToolDefinition.new(
            "subagent",
            "Spawn a child agent to handle a subtask independently.",
        ).param(
            "task",
            "string",
            "A clear description of the subtask for the child agent to complete.",
            True,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def system_prompt(self, prompt: str) -> "SubagentTool":
        self._system_prompt = prompt
        return self

    def max_turns(self, max_turns: int) -> "SubagentTool":
        self.max_turns_value = max_turns
        return self

    async def call(self, args: Any) -> str:
        task = args.get("task") if isinstance(args, dict) else None
        if not isinstance(task, str):
            raise ValueError("missing required parameter: task")

        tools = self.tools_factory()
        defs = tools.definitions()

        messages: list[Message] = []
        if self._system_prompt is not None:
            messages.append(Message.system(self._system_prompt))
        messages.append(Message.user(task))

        for _ in range(self.max_turns_value):
            turn = await self.provider.chat(messages, defs)

            if turn.stop_reason is StopReason.STOP:
                return turn.text or ""

            results: list[tuple[str, str]] = []
            for call in turn.tool_calls:
                tool = tools.get(call.name)
                if tool is None:
                    content = f"error: unknown tool `{call.name}`"
                else:
                    try:
                        content = await tool.call(call.arguments)
                    except Exception as exc:
                        content = f"error: {exc}"
                results.append((call.id, content))

            messages.append(Message.assistant(turn))
            for call_id, content in results:
                messages.append(Message.tool_result(call_id, content))

        return "error: max turns exceeded"
