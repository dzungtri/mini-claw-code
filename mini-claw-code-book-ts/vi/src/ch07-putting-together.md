# Chapter 7: A Simple CLI

You have built every important component: a mock provider for tests, four
tools, the agent loop, and an HTTP provider. Now it is time to wire them into a
working command-line assistant.

This is the chapter where the project stops feeling like individual pieces and
starts feeling like a real agent.

## Goal

Implement `chat()` in `mini-claw-code-starter-ts/src/agent.ts` and finish
`mini-claw-code-starter-ts/examples/chat.ts` so that:

1. The agent remembers the conversation across prompts.
2. The CLI prints a prompt, reads a line, runs the agent, and prints the result.
3. A `thinking...` indicator appears while the agent is working.
4. The program keeps running until the user exits or sends EOF.

## The `chat()` Method

Open [`mini-claw-code-starter-ts/src/agent.ts`](/Users/dzung/mini-claw-code/mini-claw-code-starter-ts/src/agent.ts).
You already have the `SimpleAgent` shell and the `run()` method from Chapter 5.
Chapter 7 adds a second method:

```ts
async chat(messages: Message[]): Promise<string>
```

### Why A New Method?

`run()` starts from a fresh prompt every time. That is useful for tests, but a
CLI needs conversational memory. If the user asks:

1. "Show me the files in this repo"
2. "Now open the package file"

the second prompt needs to see the first exchange.

`chat()` solves that by taking the message history from the caller. The caller
owns the array, pushes the user message, and passes the same array back on the
next turn.

In TypeScript, the shape is simpler than in Rust:

- there is no ownership move to worry about
- you mutate the same `Message[]`
- the history remains readable and explicit

That is the TS equivalent of the Rust chapter's ownership discussion.

### The Implementation

The loop body is the same as `run()`:

1. Collect tool definitions.
2. Call `provider.chat(messages, definitions)`.
3. If `stopReason === "stop"`, return the text.
4. If `stopReason === "tool_use"`, execute the tools.
5. Push the assistant turn and tool results into the history.
6. Repeat.

The important detail is that `chat()` appends the assistant turn to the same
history array that the caller passed in. That way the next user prompt still
has the entire conversation.

The implementation in the starter package is intentionally left as a TODO, but
the solution package follows this shape:

```ts
async chat(messages: Message[]): Promise<string> {
  const definitions = this.tools.definitions();

  for (;;) {
    const turn = await this.provider.chat(messages, definitions);

    if (turn.stopReason === "stop") {
      const text = turn.text ?? "";
      messages.push({ kind: "assistant", turn });
      return text;
    }

    const results = await this.executeTools(turn);
    messages.push({ kind: "assistant", turn });
    for (const result of results) {
      messages.push({ kind: "tool_result", id: result.id, content: result.content });
    }
  }
}
```

The `ToolUse` branch is the same pattern from Chapter 5: execute each tool,
catch any errors, and feed the tool outputs back into the conversation.

## The CLI

Open [`mini-claw-code-starter-ts/examples/chat.ts`](/Users/dzung/mini-claw-code/mini-claw-code-starter-ts/examples/chat.ts).
This file is the user-facing shell around the agent loop.

### Step 1: Imports

The CLI needs four things:

- the provider
- the agent
- the tools
- the message type

The starter example already imports them from `../src`:

```ts
import {
  BashTool,
  EditTool,
  OpenAICompatibleProvider,
  ReadTool,
  SimpleAgent,
  WriteTool,
  type Message,
} from "../src";
```

### Step 2: Create The Provider And Agent

The CLI asks the provider to load credentials from the environment:

```ts
const provider = OpenAICompatibleProvider.fromEnv();
const agent = SimpleAgent.new(provider)
  .tool(BashTool.new())
  .tool(ReadTool.new())
  .tool(WriteTool.new())
  .tool(EditTool.new());
```

That is the same builder pattern you have been using in the Rust book:

- create the provider
- register the tools
- keep the agent itself small

### Step 3: System Prompt And History

The user needs a stable instruction at the front of the conversation. The
starter CLI keeps it simple and inlined:

```ts
const history: Message[] = [
  {
    kind: "system",
    text: `You are a coding agent working in ${process.cwd()}.`,
  },
];
```

The system message sets the role and gives the agent the current working
directory. That makes paths in later tool calls much easier to interpret.

The `history` array lives outside the REPL loop. That is what gives the CLI
memory across turns.

### Step 4: The REPL Loop

The TypeScript starter uses `readline/promises` to read prompts:

```ts
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

const rl = readline.createInterface({ input, output });
```

The loop is straightforward:

1. Read a line.
2. Ignore empty input.
3. Exit on `/exit`.
4. Push the user message into `history`.
5. Call `agent.chat(history)`.
6. Print the answer.

The real code looks like this:

```ts
while (true) {
  const prompt = (await rl.question("> ")).trim();
  if (!prompt) {
    continue;
  }
  if (prompt === "/exit") {
    break;
  }

  history.push({ kind: "user", text: prompt });
  const result = await agent.chat(history);
  output.write(`${result}\n\n`);
}
```

The `history.push(...)` call happens before `agent.chat(...)`, so the model
sees the new prompt as part of the conversation.

### Step 5: Keep It Interactive

The CLI should feel alive, not frozen. The Rust chapter prints `thinking...`
and clears it when the answer is ready. The same idea applies here.

In TypeScript, `process.stdout.write()` is usually the easiest way to avoid
extra newlines and keep control of the cursor.

### Why The History Stays Outside The Agent

This is a design boundary, not a convenience accident.

- The agent should own orchestration.
- The CLI should own interaction.
- The `history` array should live in the place that decides when the
  conversation resets.

That makes the code easier to reason about and easier to test. The same agent
can then be reused by scripts, REPLs, and later the TUI.

### Why This Still Feels Like A Coding Assistant

The CLI has three little details that matter a lot in practice:

1. The prompt is short and familiar.
2. The assistant answer is appended to the same conversation.
3. The user can keep talking without reloading state.

That combination is what makes a terminal program feel like an assistant
instead of a one-shot script.

### The Example In The Repository

The starter example uses the same structure as the solution package:

```ts
const rl = readline.createInterface({ input, output });
const history: Message[] = [
  {
    kind: "system",
    text: `You are a coding agent working in ${process.cwd()}.`,
  },
];

while (true) {
  const prompt = (await rl.question("> ")).trim();
  if (!prompt) {
    continue;
  }
  if (prompt === "/exit") {
    break;
  }

  history.push({ kind: "user", text: prompt });
  const result = await agent.chat(history);
  output.write(`${result}\n\n`);
}
```

The example keeps the system prompt inline so students can focus on the loop
before moving on to later chapters where prompt loading becomes a reusable
helper.

## Testing The Chapter

Run the Chapter 7 starter test directly:

```bash
bun test mini-claw-code-starter-ts/tests/ch7.test.ts
```

That test checks the conversation-history behavior of `chat()`. When the
chapter is finished, the CLI should also work manually:

```bash
bun run mini-claw-code-starter-ts/examples/chat.ts
```

If you want to run the whole starter suite, use:

```bash
bun run --cwd mini-claw-code-starter-ts test
```

The important Chapter 7 checks are:

- a first prompt adds one user message and one assistant response
- a second prompt sees the previous context
- tool calls still work while the history grows
- `"/exit"` stops the loop cleanly

These are small assertions, but together they prove that the CLI is doing the
right thing with state.

## The Full Picture

Once the loop works, the flow is simple:

```text
user input
  -> push to history
  -> agent.chat(history)
  -> provider.chat(...)
  -> maybe execute tools
  -> append assistant and tool results
  -> return text
```

Nothing in that flow is special to the terminal. The same pattern can drive a
web UI, a background job, or a later TUI.

## What You Have Built

By the end of Chapter 7, the project should look like this:

```text
examples/chat.ts
    |
    | creates
    v
SimpleAgent<OpenAICompatibleProvider>
    |
    | holds
    +---> OpenAICompatibleProvider (HTTP to model API)
    +---> ToolSet (Map<string, Tool>)
              |
              +---> BashTool
              +---> ReadTool
              +---> WriteTool
              +---> EditTool
```

The `chat()` method is the key. It takes a history array, calls the provider,
executes tools when needed, and appends everything back into the same
conversation.

That is enough to build a usable local coding assistant.

## Recap

- `run()` starts a fresh prompt.
- `chat()` continues an existing conversation.
- The CLI owns the `history` array and passes it into the agent.
- Bun's `readline/promises` makes the REPL easy to read.
- The system prompt gives the model its role and the current working
  directory.

This finishes the first half of the TypeScript book. The next chapters add
streaming, better terminal UX, user input, plan mode, subagents, and safety.
