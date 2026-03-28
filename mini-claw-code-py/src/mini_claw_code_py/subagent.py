from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .types import Message, Provider, StopReason, ToolDefinition, ToolSet


SUBAGENT_PARENT_PROMPT_SECTION = """<subagent_system>
You can delegate focused multi-step work to a child agent with the `subagent` tool.

The user does not need to ask for a subagent explicitly. If delegation is the
best way to isolate context or complete a bounded task, use it proactively.

Use `subagent` when:
- the task is self-contained and needs several steps
- the task would create too much local context for the parent
- the parent mainly needs a concise summary of the result
- the work is a single large context-heavy branch that can be isolated cleanly

Do not use `subagent` when:
- the task is trivial or single-step
- the task needs direct user clarification first

When you delegate:
1. Write a clear task brief with the goal, scope, useful context, constraints, and expected output.
2. Let the child complete the task independently.
3. Use the returned summary to continue the parent task.
</subagent_system>"""


def render_harness_subagent_prompt_section(max_parallel_subagents: int) -> str:
    return f"""<subagent_orchestration>
You have bundled subagent support in the harness runtime.

Your role is not only to use tools directly. Your role is to be a small task
orchestrator:
1. DECOMPOSE multi-part work into sensible child tasks
2. DELEGATE bounded child tasks when that improves focus or context isolation
3. SYNTHESIZE child results into one coherent answer

The user does not need to mention `subagent`. If delegation is the better
execution strategy, choose it yourself.

Prefer `subagent` when:
- the task is complex, self-contained, and needs several steps
- the task can be broken into two or more independent branches
- the task is a single large context-heavy branch that would overload the parent
- the parent mainly needs a concise returned summary, not the full child history

Do not use `subagent` when:
- the task is trivial or single-step
- the task needs direct user clarification first
- direct tool use is simpler than delegation

Orchestration rules:
1. The parent still owns the task and must synthesize child results.
2. Give each child a clear brief with scope, constraints, and expected output.
3. Keep child scope narrow and tool use bounded.
4. Prefer direct tool use for trivial work such as one quick read, one exact edit, or one simple command.
5. Launch at most {max_parallel_subagents} subagent call(s) in one parent turn.
6. If there are more child-worthy tasks than that, batch them across turns.

Examples:
- "Compare three large implementation options" -> delegate one child per option, then synthesize.
- "Analyze one large repository area and summarize findings" -> one subagent is appropriate for context isolation.
- "Read one small file and answer a question" -> do it directly, no subagent.
</subagent_orchestration>"""


DEFAULT_SUBAGENT_SYSTEM_PROMPT = """You are a delegated subagent working on a focused task.

Guidelines:
- Complete the delegated task autonomously using the provided tools.
- Keep your work scoped to the task you were given.
- Do not ask the user for clarification. Work with the information in the task.
- Return a concise, actionable result for the parent agent.
- If you hit a real blocker, explain it clearly in your final answer.
"""


@dataclass(slots=True)
class SubagentRuntimeConfig:
    tools: ToolSet
    system_prompt: str | None
    max_turns: int
    profile_name: str = "general-purpose"


class SubagentTool:
    def __init__(
        self,
        provider: Provider,
        tools_factory: Callable[[], ToolSet],
        *,
        runtime_config_factory: Callable[[str | None], SubagentRuntimeConfig] | None = None,
    ) -> None:
        self.provider = provider
        self.tools_factory = tools_factory
        self._system_prompt: str | None = DEFAULT_SUBAGENT_SYSTEM_PROMPT
        self.max_turns_value = 10
        self._runtime_config_factory = runtime_config_factory
        self._definition = ToolDefinition.new(
            "subagent",
            "Delegate a focused multi-step subtask to a child agent with its own message history and tools.",
        ).param(
            "task",
            "string",
            "A clear delegated task for the child agent, including the goal, useful context, and expected output.",
            True,
        ).param(
            "subagent_type",
            "string",
            "Optional configured subagent type. Omit to use the general-purpose child.",
            False,
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
        subagent_type = args.get("subagent_type") if isinstance(args, dict) else None
        if not isinstance(task, str):
            raise ValueError("missing required parameter: task")
        if subagent_type is not None and not isinstance(subagent_type, str):
            raise ValueError("subagent_type must be a string")

        runtime = self._resolve_runtime(subagent_type)
        defs = runtime.tools.definitions()
        messages = self._initial_messages(task, runtime.system_prompt)

        for _ in range(runtime.max_turns):
            turn = await self.provider.chat(messages, defs)

            if turn.stop_reason is StopReason.STOP:
                return turn.text or ""

            results = await self._execute_child_tools(runtime.tools, turn.tool_calls)
            self._push_results(messages, turn, results)

        return "error: max turns exceeded"

    def _initial_messages(self, task: str, system_prompt: str | None) -> list[Message]:
        messages: list[Message] = []
        if system_prompt is not None:
            messages.append(Message.system(system_prompt))
        messages.append(Message.user(task))
        return messages

    def _resolve_runtime(self, subagent_type: str | None) -> SubagentRuntimeConfig:
        if self._runtime_config_factory is not None:
            return self._runtime_config_factory(subagent_type)
        return SubagentRuntimeConfig(
            tools=self.tools_factory(),
            system_prompt=self._system_prompt,
            max_turns=self.max_turns_value,
        )

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
