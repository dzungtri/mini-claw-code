# Chapter 11: User Input

Your agent can read files, run commands, and edit code, but it cannot ask the
human a question unless you give it a tool for that. Without user input, the
model has to guess when a filename is unclear, when a choice has multiple
reasonable answers, or when a destructive action needs approval.

Real coding agents solve this with an ask tool. The LLM calls a special tool,
the agent pauses, and the user answers. The answer is fed back as a tool
result and the loop continues.

In this chapter you will build:

1. An `InputHandler` interface that abstracts how user input is collected.
2. An `AskTool` that the LLM calls to ask the user a question.
3. Three handler implementations: CLI, TUI bridge, and mock.

## Why A Handler Interface?

Different frontends collect input in different ways:

- A CLI app prints a prompt to stdout and reads from stdin.
- A TUI app usually needs to hand the question to its event loop.
- Tests need canned answers with no real I/O.

The `InputHandler` interface keeps `AskTool` independent of the frontend:

```ts
export interface InputHandler {
  ask(question: string, options: string[]): Promise<string>;
}
```

The `question` is the text from the model. The `options` array is optional. If
it is empty, the user types free text. If it is not empty, the UI can present a
list of choices.

This is the same idea as the Rust chapter: the tool should not know whether the
answer came from the terminal, a channel, or a test stub.

## AskTool

`AskTool` is the bridge between the model and the human. It exposes a tool
called `ask_user`, accepts a required `question`, and accepts an optional
`options` array.

The TypeScript version uses the same schema ideas as the Rust version, but the
types are simpler:

```ts
export class AskTool implements Tool {
  constructor(private readonly handler: InputHandler) {}

  definition(): ToolDefinition {
    return new ToolDefinition(
      "ask_user",
      "Ask the user a clarifying question before proceeding.",
    )
      .param("question", "string", "The question to ask the user", true)
      .paramRaw(
        "options",
        {
          type: "array",
          items: { type: "string" },
          description: "Optional list of choices to present to the user",
        },
        false,
      );
  }
}
```

The `question` parameter is required. The `options` parameter is optional and
uses `paramRaw()` because arrays are more expressive than a simple scalar
builder can represent.

### Tool Call Flow

The `call()` method does three things:

1. Validate that `question` is a string.
2. Parse the optional `options` array into a `string[]`.
3. Delegate to the injected `InputHandler`.

That keeps the tool focused on the contract instead of the UI details.

```ts
async call(args: JsonValue): Promise<string> {
  const question = (args as { question?: unknown }).question;
  if (typeof question !== "string") {
    throw new Error("missing required parameter: question");
  }

  const options =
    Array.isArray((args as { options?: unknown }).options)
      ? (args as { options: unknown[] }).options.filter(
          (value): value is string => typeof value === "string",
        )
      : [];

  return await this.handler.ask(question, options);
}
```

The point is not the exact syntax. The point is that the model can now pause
the loop and ask the human for missing information.

## CliInputHandler

The simplest handler prints a prompt and waits for stdin. In Bun you can do
that with `readline/promises`, or with a small wrapper around standard input.
The implementation in `mini-claw-code-ts/src/tools/ask.ts` uses a direct
question/answer flow and resolves numbered options when the user types `1`,
`2`, and so on.

The important behavior is:

- show the question
- list the options when provided
- let the user type free text when there are no options
- convert a numeric answer back into the matching option

That makes the CLI version usable both for open-ended questions and for
approval prompts.

## ChannelInputHandler

The TUI version needs to hand the request to an outer event loop. In the Rust
book that is done with channels and oneshot responses. In the TypeScript
version, the same idea is expressed as a request/response callback bridge.

The shape is still the same:

```ts
export interface UserInputRequest {
  question: string;
  options: string[];
}

export class ChannelInputHandler implements InputHandler {
  constructor(
    private readonly dispatch: (request: UserInputRequest) => Promise<string>,
  ) {}

  ask(question: string, options: string[]): Promise<string> {
    return this.dispatch({ question, options });
  }
}
```

The tool does not care how the answer is rendered. It only cares that the TUI
event loop eventually returns a string.

This is the key abstraction: the agent asks, the UI decides how to present the
question, and the answer comes back as plain text.

## MockInputHandler

For tests, a fake input handler keeps the chapter deterministic:

```ts
export class MockInputHandler implements InputHandler {
  constructor(answers: Iterable<string>) {
    this.answers = [...answers];
  }

  async ask(_question: string, _options: string[]): Promise<string> {
    const answer = this.answers[this.cursor];
    if (answer === undefined) {
      throw new Error("MockInputHandler: no more answers");
    }
    this.cursor += 1;
    return answer;
  }
}
```

That lets you test asking, option selection, and exhaustion behavior without
any terminal interaction.

## Tool Summary

The tool summary logic from the agent loop is worth mentioning here because it
becomes much more useful once `ask_user` exists. When the agent asks the human
a question, the UI can show the question summary just like a tool call summary,
which keeps the interaction readable.

In other words: `AskTool` is not a special case. It is just another tool that
returns a string result, and the agent loop handles it the same way as `read`
or `bash`.

## Plan Mode Integration

`ask_user` is especially valuable in plan mode. When the model is exploring a
change, it may need to ask:

- which file is the right target
- whether a rewrite is allowed
- which of several approaches the user prefers

That is why `ask_user` belongs in the read-only tool set for planning.

## Wiring It Up

Export the types and the tool from `mini-claw-code-ts/src/tools/index.ts`, then
register `AskTool` in any agent that needs user interaction.

```ts
const agent = new SimpleAgent(provider)
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(new CliInputHandler()));
```

The same tool also works in the planning agent and the TUI. Only the handler
changes.

## Implementation Details

The Rust chapter spends a lot of time on small helpers because they keep the
tool easy to reason about. The TypeScript version should do the same.

### Option Resolution

When the user types `1`, `2`, or `3`, the CLI should map that number back to
the matching choice. If the input is not a valid number, the raw text should be
used as-is.

```ts
function resolveOption(answer: string, options: string[]): string {
  const asNumber = Number(answer);
  if (Number.isInteger(asNumber) && asNumber >= 1 && asNumber <= options.length) {
    return options[asNumber - 1]!;
  }
  return answer;
}
```

That helper makes the CLI version usable for both free-text answers and
approval prompts.

### The CLI Boundary

The CLI handler should keep its I/O boundary small:

1. render the question
2. list the choices when provided
3. read a line from stdin
4. resolve numbered answers back into the choice list

That keeps the user-facing code separate from the agent logic.

### The TUI Bridge

The TUI should not ask directly from inside the tool. It should pass the
request outward and let the event loop render it in whatever style it wants.

That is why `ChannelInputHandler` is just a thin adapter around a dispatch
function. The request object contains the question and option list, and the UI
event loop decides how to display them.

### Mock Answers

The mock handler should use a simple queue of answers. That gives the tests a
deterministic way to verify:

- free-text answers
- option selection
- repeated questions
- exhaustion errors

The whole point is to keep the chapter testable without real terminal I/O.

## Tool Summary

The tool summary logic from the agent loop becomes much more useful once
`ask_user` exists. When the agent asks the human a question, the UI can show
the question summary just like a tool call summary.

In other words: `AskTool` is not a special case. It is just another tool that
returns a string result, and the agent loop handles it the same way as `read`
or `bash`.

## Plan Mode Integration

`ask_user` is especially valuable in plan mode. When the model is exploring a
change, it may need to ask:

- which file is the right target
- whether a rewrite is allowed
- which of several approaches the user prefers

That is why `ask_user` belongs in the read-only tool set for planning.

## Wiring It Up

Export the types and the tool from `mini-claw-code-ts/src/tools/index.ts`, then
register `AskTool` in any agent that needs user interaction.

```ts
const agent = new SimpleAgent(provider)
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(new CliInputHandler()));
```

The same tool also works in the planning agent and the TUI. Only the handler
changes.

## Testing

Run the chapter 11 tests:

```bash
bun test mini-claw-code-starter-ts/tests/ch11.test.ts
```

The tests verify:

- the tool definition exposes `question` and optional `options`
- the CLI handler resolves option numbers
- the mock handler returns canned answers
- the ask tool delegates to the handler

## Recap

- `InputHandler` keeps the tool independent from the frontend.
- `AskTool` lets the model ask the human a question instead of guessing.
- `CliInputHandler`, `ChannelInputHandler`, and `MockInputHandler` cover the
  three main runtime environments.
- `ask_user` is a normal tool, which means the agent loop does not need a
  special case for human input.
