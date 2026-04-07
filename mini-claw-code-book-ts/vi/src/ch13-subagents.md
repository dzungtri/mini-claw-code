# Chapter 13: Subagents

Complex tasks are easier when the main agent can delegate focused work to a
child agent.

If you ask one model to research, design, code, and verify everything in one
conversation, it will often lose focus. The context gets crowded, the model
forgets details from earlier turns, and the quality drops.

Subagents solve that by decomposition: the parent agent spawns a child agent
for a single subtask. The child gets its own messages and tools, runs to
completion, and returns a concise result. The parent sees only the summary.

That is the same pattern used by Claude Code's Task tool and by other agentic
tools that need to break work into smaller pieces.

In this chapter you will build `SubagentTool`, a `Tool` implementation that
spawns ephemeral child agents.

## Why Subagents Help

Consider this request:

> Add error handling to all API endpoints.

Without subagents, the parent agent may:

- read many files
- lose track of what it already changed
- mix implementation and verification in one long loop
- produce inconsistent edits

With subagents, the parent can delegate focused tasks:

- one child reviews the users endpoint
- another child reviews the posts endpoint
- a third child verifies the error shape

The parent stays in control and the child results stay focused.

## Provider Sharing

The parent and child should use the same provider configuration. In TypeScript
that is simple: the provider is just an object reference, so you can reuse it
without cloning any network client.

The child only needs a fresh tool set and a fresh message history.

## The Shape

`SubagentTool` needs four pieces of state:

```ts
export class SubagentTool implements Tool {
  constructor(
    private readonly provider: Provider,
    private readonly toolsFactory: () => ToolSet,
  ) {}

  private systemPromptText?: string;
  private maxTurns = 10;
  private readonly definition = new ToolDefinition(
    "subagent",
    "Spawn a child agent to handle a subtask independently.",
  ).param("task", "string", "A clear description of the subtask.", true);
}
```

Three of those are worth highlighting:

- the provider is shared
- the tool factory produces a fresh `ToolSet` for each child
- `maxTurns` prevents runaway loops

The factory matters because tool objects are not meant to be shared across
children by accident. Each child should get a clean set of tools for its own
task.

## The Builder

The builder matches the rest of the codebase:

```ts
systemPrompt(prompt: string): this
maxTurns(value: number): this
```

That keeps the tool composable and lets callers specialize child behavior when
needed.

## The Tool Call

The `call()` method does a small amount of validation and then runs an inner
agent loop:

1. extract the `task`
2. create a fresh tool set
3. build a fresh message history
4. run the child provider until it stops or hits `maxTurns`
5. return the final text to the parent

The child agent does not share its intermediate messages with the parent. Only
the final answer crosses the boundary.

That is important. It keeps the parent conversation small and prevents child
noise from leaking into the main loop.

### Minimal Child Loop

The child loop is intentionally the same core loop as the parent, just scoped
to a different message history:

```ts
for (let turn = 0; turn < this.maxTurns; turn += 1) {
  const assistantTurn = await this.provider.chat(messages, definitions);
  if (assistantTurn.stopReason === "stop") {
    return assistantTurn.text ?? "";
  }

  // execute tool calls, append assistant + tool results, continue
}
```

That keeps the mental model small. A subagent is not a new runtime. It is just
another use of the same loop.

## Why No Background Task?

It is tempting to spawn a background task or a worker thread for the child.
This book does not need that complexity.

Running the child inline keeps the behavior predictable:

- no extra cancellation logic
- no join handle management
- no message broker
- no race conditions between parent and child

The child is just a nested agent call.

That also makes the tool easier to test. A child agent is not a new runtime
primitive; it is just a nested call path you can exercise with a mock provider.

## Example

The parent can give the child a specialized prompt when it needs a narrower
focus:

```ts
const tool = new SubagentTool(provider, () =>
  ToolSet.from(new ReadTool(), new WriteTool(), new BashTool()),
).systemPrompt("You are a security reviewer. Focus on vulnerabilities.");
```

That gives the parent a reusable way to delegate focused work without changing
the parent loop.

You can also narrow the child's tool set. For exploratory tasks, a child might
only get `read` and `bash`. For write-heavy tasks, it might get `read`,
`write`, and `bash`. The closure-based factory keeps that decision local.

## Wiring It Up

The parent registers `SubagentTool` like any other tool:

```ts
const agent = new SimpleAgent(provider)
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new BashTool())
  .tool(
    new SubagentTool(provider, () =>
      ToolSet.from(new ReadTool(), new WriteTool(), new BashTool()),
    ),
  );
```

The parent still owns the top-level workflow. The child only handles the
subtask that was delegated.

## Important Constraints

Subagents are useful, but they should stay disciplined:

- each child gets a fresh tool set
- the provider is reused, not recreated
- the child must have a bounded turn count
- the parent should only see the final answer

Those constraints make delegation predictable and keep the parent loop easy to
reason about.

## Testing

Run the chapter 13 tests:

```bash
bun test mini-claw-code-starter-ts/tests/ch13.test.ts
```

The tests verify:

- the child returns text directly
- the child can use tools before answering
- multi-step child conversations work
- the turn limit is enforced
- missing tasks are rejected
- provider errors propagate

Those cases cover the happy path and the main failure modes. If a child leaks
its internal messages or runs forever, the parent agent becomes much harder to
trust.

Those tests matter because delegation bugs can be subtle. A broken child loop
can look like a normal tool error, so the chapter should prove both the happy
path and the failure path.

## Recap

- Subagents break large tasks into focused child conversations.
- The parent only sees the child's final answer.
- A fresh tool set keeps child scope clean.
- A turn limit keeps the nested loop bounded.
- In TypeScript, provider reuse is simple because object references are shared.
- A child agent is still just the same core loop, nested one level deeper.
- The parent stays simpler because the child owns the focused subtask.
- Delegation is an architectural boundary, not a new runtime primitive.
