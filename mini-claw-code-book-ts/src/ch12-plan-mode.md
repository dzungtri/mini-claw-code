# Chapter 12: Plan Mode

Real coding agents are dangerous if they can write files immediately. Give the
model `write`, `edit`, and `bash`, and it can change your repo before the human
has had a chance to review the approach.

Plan mode solves that by splitting the workflow into two phases:

1. plan with read-only tools
2. execute after approval

This is the same idea as Claude Code's plan mode and OpenCode's approval
workflow. In this chapter you will build `PlanAgent`, a streaming agent with
caller-driven approval gating.

## Why Plan Mode Exists

Consider this request:

> Refactor the auth layer to use JWT instead of session cookies.

Without plan mode, the model might immediately start writing code. That is a
bad default because there are often several valid approaches:

- replace the session store directly
- introduce a compatibility layer
- split the work into multiple files
- ask a follow-up question before editing

Plan mode forces the model to explore first and explain its intent before it
touches the filesystem.

## The Design

`PlanAgent` has the same broad shape as `StreamingAgent`: a provider, a
`ToolSet`, and a loop. The additions are what make it safe:

```ts
export class PlanAgent {
  constructor(
    private readonly provider: StreamProvider,
    private readonly tools = new ToolSet(),
  ) {
    this.readOnly = new Set(["bash", "read", "ask_user"]);
    this.planPromptText = DEFAULT_PLAN_PROMPT_TEMPLATE;
    this.exitPlanDefinition = new ToolDefinition(
      "exit_plan",
      "Signal that your plan is complete and ready for user review.",
    );
  }

  readOnly: Set<string>;
  planPromptText: string;
  exitPlanDefinition: ToolDefinition;

  plan(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {}
  execute(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {}
}
```

Three pieces matter:

- a set of tool names allowed during planning
- a system prompt that tells the model it is in planning mode
- an `exit_plan` tool definition that the model can call when it is done

## The Builder

The builder methods follow the same style as `SimpleAgent` and
`StreamingAgent`:

```ts
planPrompt(prompt: string): this
readOnlyTools(names: string[]): this
tool(tool: Tool): this
```

The defaults are intentionally narrow:

- `bash`
- `read`
- `ask_user`

Those are enough for exploration and clarification, but not enough to modify
the codebase.

## The Planning Prompt

The model needs to know that it is in planning mode. Without that instruction
it will try to complete the task with whatever tools it sees.

The planning prompt should say, in plain language:

- you are in planning mode
- you may inspect the codebase
- you may ask the user questions
- you may not write, edit, or create files
- when the plan is ready, call `exit_plan`

The prompt is injected only if the conversation does not already begin with a
system message. That lets callers provide their own specialized prompt when
needed.

## The `exit_plan` Tool

`exit_plan` is a deliberate signal from the model. It is clearer than relying
on `stopReason === "stop"` because a stop could mean many things:

- the model finished planning
- the model ran out of tokens
- the model stalled

The `exit_plan` tool says: "the plan is ready for review."

In the TypeScript implementation, `exit_plan` is a `ToolDefinition` stored on
the agent, not a regular registered tool. That lets `plan()` expose it and
`execute()` hide it.

The child loop is still the same agent loop the book introduced earlier. The
tool list and the exit condition are the only things that change.

## The Shared Loop

`PlanAgent` keeps one loop and two modes. That is the important architectural
choice.

The loop does the usual steps:

1. ask the provider for the next turn
2. inspect `stopReason`
3. execute tool calls if needed
4. append assistant and tool-result messages
5. continue until the model stops or exits planning

Only the tool filter changes between phases. Everything else stays the same.

That is the same trick used in the Rust book: the core loop stays stable, and
the safety boundary is expressed as a tool list plus one extra exit condition.

## The Shared Loop In Practice

The private loop is easy to describe in code:

```ts
const definitions =
  allowed === undefined
    ? this.tools.definitions()
    : [
        ...this.tools
          .definitions()
          .filter((definition) => allowed.has(definition.name)),
        this.exitPlanDefinition,
      ];

for (;;) {
  const turn = await this.provider.streamChat(messages, definitions, onStream);

  if (turn.stopReason === "stop") {
    messages.push(assistantMessage(turn));
    return turn.text ?? "";
  }

  // handle exit_plan and blocked tools here
}
```

There are only two moving parts:

- which tools are visible to the model
- whether `exit_plan` was called

Everything else is just the ordinary agent protocol the book has already
introduced.

## Double Defense

Plan mode uses two layers of protection.

### Layer 1: Definition Filtering

During planning, only read-only tools plus `exit_plan` are passed to the
provider. The model cannot see `write` or `edit` in its tool list.

That means the model's available options are constrained before it even makes a
decision.

### Layer 2: Execution Guard

The execution guard checks each tool call before running it. If the model
somehow hallucinated a blocked tool, the agent returns an error string instead
of executing the call.

That keeps the model informed and the filesystem safe.

This matters because the model can still sometimes invent a blocked tool call
or remember a tool name from an older turn. The guard turns that mistake into a
recoverable result instead of a filesystem change.

## The Shared Loop

Both phases use the same loop. The only difference is which tools are visible.
`plan()` passes the read-only set. `execute()` passes no filter and exposes the
full tool set.

That means the architecture stays simple:

1. provider request
2. inspect stop reason
3. run tools if needed
4. append assistant and tool-result messages
5. repeat

The loop never changes. Only the tool filter changes.

## Caller-Driven Approval

`PlanAgent` does not ask for approval itself. The caller owns that flow.

That keeps the agent focused on orchestration and lets the UI decide how to
present the plan:

- a CLI prompt
- a TUI confirmation
- a web approval screen

The important part is that the same `messages` array is reused across phases,
so the model sees its own plan and the user's feedback when execution begins.

If the user wants a revision, the caller can append feedback as a `User`
message and call `plan()` again. That keeps the model's context continuous.

That reuse is what makes the flow feel coherent. The model can review its own
plan, get rejected, and then refine the same conversation instead of starting
from scratch.

## Caller-Driven Approval Example

The caller owns the approval UI. The agent just produces the plan and executes
when asked:

```ts
const messages: Message[] = [userMessage("Refactor auth.ts")];

const plan = await agent.plan(messages, onEvent);
console.log("Plan:", plan);

if (userApproves(plan)) {
  messages.push(userMessage("Approved. Execute the plan."));
  const result = await agent.execute(messages, onEvent);
  console.log(result);
} else {
  messages.push(userMessage("Try a different approach."));
  const revisedPlan = await agent.plan(messages, onEvent);
  console.log("Revised plan:", revisedPlan);
}
```

This is exactly the sort of workflow real agents need in practice: first
explore, then ask, then mutate only after the human agrees.

## Wiring It Up

The planning agent uses the same tools as the regular agent, but only the
read-only subset is available during plan mode. The TS examples and tests use
the same pattern:

```ts
const agent = new PlanAgent(provider)
  .planPrompt(planPrompt)
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(handler));
```

The caller decides when to call `plan()` and when to call `execute()`.

## Testing

Run the chapter 12 tests:

```bash
bun test mini-claw-code-starter-ts/tests/ch12.test.ts
```

The tests verify:

- the planning prompt is injected when needed
- the read-only tool set is enforced
- `exit_plan` ends the planning phase
- the execute phase can run with the full tool set

## Recap

- Plan mode separates exploration from mutation.
- The model only sees safe tools during planning.
- `exit_plan` gives the model an explicit way to hand off a plan.
- The caller owns the approval flow and chooses when execution starts.
