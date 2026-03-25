from __future__ import annotations

from typing import Any, Callable

from .types import Message, Provider, StopReason, ToolDefinition, ToolSet


SUBAGENT_PARENT_PROMPT_SECTION = """<subagent_system>
You can delegate focused multi-step work to a child agent with the `subagent` tool.

Use `subagent` when:
- the task is self-contained and needs several steps
- the task would create too much local context for the parent
- the parent mainly needs a concise summary of the result

Do not use `subagent` when:
- the task is trivial or single-step
- the task needs direct user clarification first

When you delegate:
1. Write a clear task brief with the goal, scope, useful context, constraints, and expected output.
2. Let the child complete the task independently.
3. Use the returned summary to continue the parent task.
</subagent_system>"""


DEFAULT_SUBAGENT_SYSTEM_PROMPT = """You are a delegated subagent working on a focused task.

Guidelines:
- Complete the delegated task autonomously using the provided tools.
- Keep your work scoped to the task you were given.
- Do not ask the user for clarification. Work with the information in the task.
- Return a concise, actionable result for the parent agent.
- If you hit a real blocker, explain it clearly in your final answer.
"""


class SubagentTool:
    def __init__(self, provider: Provider, tools_factory: Callable[[], ToolSet]) -> None:
        self.provider = provider
        self.tools_factory = tools_factory
        self._system_prompt: str | None = DEFAULT_SUBAGENT_SYSTEM_PROMPT
        self.max_turns_value = 10
        self._definition = ToolDefinition.new(
            "subagent",
            "Delegate a focused multi-step subtask to a child agent with its own message history and tools.",
        ).param(
            "task",
            "string",
            "A clear delegated task for the child agent, including the goal, useful context, and expected output.",
            True,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def system_prompt(self, prompt: str) -> "SubagentTool":
        self._system_prompt = prompt
        return self

    def max_turns(self, max_turns: int) -> "SubagentTool":
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.max_turns_value = max_turns
        return self

    async def call(self, args: Any) -> str:
        task = args.get("task") if isinstance(args, dict) else None
        if not isinstance(task, str):
            raise ValueError("missing required parameter: task")

        tools = self.tools_factory()
        defs = tools.definitions()

        messages = self._initial_messages(task)

        for _ in range(self.max_turns_value):
            turn = await self.provider.chat(messages, defs)

            if turn.stop_reason is StopReason.STOP:
                return turn.text or ""

            results = await self._execute_child_tools(tools, turn.tool_calls)
            self._push_results(messages, turn, results)

        return "error: max turns exceeded"

    def _initial_messages(self, task: str) -> list[Message]:
        messages: list[Message] = []
        if self._system_prompt is not None:
            messages.append(Message.system(self._system_prompt))
        messages.append(Message.user(task))
        return messages

    async def _execute_child_tools(
        self,
        tools: ToolSet,
        calls: list[Any],
    ) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for call in calls:
            tool = tools.get(call.name)
            if tool is None:
                content = f"error: unknown tool `{call.name}`"
            else:
                try:
                    content = await tool.call(call.arguments)
                except Exception as exc:
                    content = f"error: {exc}"
            results.append((call.id, content))
        return results

    @staticmethod
    def _push_results(
        messages: list[Message],
        turn: Any,
        results: list[tuple[str, str]],
    ) -> None:
        messages.append(Message.assistant(turn))
        for call_id, content in results:
            messages.append(Message.tool_result(call_id, content))


def render_subagent_prompt_section() -> str:
    return SUBAGENT_PARENT_PROMPT_SECTION
