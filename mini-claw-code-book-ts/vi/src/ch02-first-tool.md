# Chapter 2: Your First Tool

Now you will build the first real tool: `ReadTool`.

This tool reads a file from disk and returns its contents as a string. It is a
small chapter, but it matters because it introduces the full tool contract:

- tool definition
- tool arguments
- tool execution
- error handling

Once `ReadTool` exists, the model can inspect project files instead of
guessing.

## Goal

Implement `ReadTool` so that:

1. it exposes a `ToolDefinition` named `"read"`
2. it requires a `"path"` parameter of type `"string"`
3. `call()` reads the file from disk and returns its contents
4. it throws if the path is missing or the file cannot be read

## The `Tool` interface

Open `mini-claw-code-starter-ts/src/types.ts`. The tool interface is:

```ts
export interface Tool {
  definition(): ToolDefinition
  call(args: JsonValue): Promise<string>
}
```

Every tool has two responsibilities:

- **`definition()`** tells the model the tool exists and describes how to call it
- **`call(args)`** actually performs the work

That split is important.

The model sees only the definition. Your runtime sees only the actual
implementation. The agent loop connects the two later.

## `ReadTool`

Open `mini-claw-code-starter-ts/src/tools/read.ts`.

The scaffold already gives you the class shape:

```ts
export class ReadTool implements Tool {
  readonly toolDefinition: ToolDefinition

  constructor() {
    this.toolDefinition = ToolDefinition.new(
      "read",
      "Read the contents of a file.",
    ).param("path", "string", "The file path to read", true)
  }

  definition(): ToolDefinition {
    return this.toolDefinition
  }

  async call(_args: JsonValue): Promise<string> {
    throw new Error("TODO...")
  }
}
```

You only need to finish the runtime logic.

## Key TypeScript concepts

### Narrowing `JsonValue`

The tool API accepts `JsonValue`, because tool arguments are JSON-shaped.

That means `args` is not automatically known to be an object with a `path`
field. You need to narrow it first.

Typical pattern:

```ts
if (
  typeof args !== "object" ||
  args === null ||
  Array.isArray(args) ||
  typeof args.path !== "string"
) {
  throw new Error("missing 'path' argument")
}
```

This is the TypeScript equivalent of validating JSON input before you trust it.

### `node:fs/promises`

The implementation uses:

```ts
import { readFile } from "node:fs/promises"
```

`readFile(path, "utf8")` returns a `Promise<string>`, which fits the `Tool`
contract naturally.

## The implementation

Open `mini-claw-code-starter-ts/src/tools/read.ts`.

### Step 1: Validate the arguments

The `path` argument must exist and must be a string.

If the argument shape is wrong, throw a descriptive error such as:

```ts
throw new Error("missing 'path' argument")
```

That message is useful because later chapters catch tool errors and feed them
back to the model as tool results.

### Step 2: Read the file

Once `path` is known to be a string:

```ts
return readFile(path, "utf8")
```

That is enough.

If the file does not exist, `readFile` rejects and the tool call fails. That is
fine. You do not need custom recovery logic here.

## Why return file contents as a string?

Because the model consumes text.

Even though the tool is "reading a file," the real point is:

> "Turn something from the outside world into text the model can reason about."

That same pattern shows up again and again:

- `read` turns file contents into text
- `bash` turns command output into text
- `ask_user` turns user input into text

The model always works by receiving more text context.

## Running the tests

Run the Chapter 2 tests:

```bash
bun test mini-claw-code-starter-ts/tests/ch2.test.ts
```

### What the tests verify

- the tool definition is named `"read"`
- the `path` parameter is required
- the tool returns file contents

This chapter is deliberately small. It is the minimal example of the tool
pattern.

## Recap

- A tool has two halves: schema and runtime behavior.
- `ReadTool` is the first concrete example of the tool interface.
- Tool arguments arrive as generic JSON and must be narrowed before use.
- The model does not read files itself; your runtime does it and returns text.

In the next chapter, you will connect this tool to a provider for the first
time.
