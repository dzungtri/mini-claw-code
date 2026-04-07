# Chapter 2: Your First Tool

Now that you have a mock provider, it is time to build your first tool. You
will implement `ReadTool`: a tool that reads a file and returns its contents.

This is the simplest tool in the framework, but it introduces the pattern every
other tool follows.

## Goal

Implement `ReadTool` so that:

1. it declares its name, description, and parameter schema
2. when called with `{"path": "some/file.txt"}`, it reads the file
3. it returns the contents as a string
4. missing arguments or missing files become useful errors

## The tool pattern

Open `mini-claw-code-starter-py/src/mini_claw_code_starter_py/tools/read.py`.

Every tool has the same structure:

```python
class ReadTool:
    @property
    def definition(self) -> ToolDefinition:
        ...

    async def call(self, args: Any) -> str:
        ...
```

The model never touches the filesystem itself. It produces a structured request,
your tool executes it, and the result comes back as plain text.

```mermaid
flowchart LR
    A["LLM emits ToolCall"] --> B["args = {'path': 'f.txt'}"]
    B --> C["ReadTool.call(args)"]
    C --> D["file contents"]
    D --> E["tool result sent back to LLM"]
```

## `ToolDefinition`

As in Chapter 1, the tool schema uses the builder API:

```python
ToolDefinition.new("read", "Read the contents of a file.").param(
    "path", "string", "The file path to read", True
)
```

That says:

- the tool is called `read`
- it expects a single required parameter called `path`
- `path` must be a string

## Async file I/O in Python

Python's standard library does not provide a native async file API like Tokio.
The simplest approach is to use `asyncio.to_thread()` to run blocking file work
in a worker thread:

```python
content = await asyncio.to_thread(Path(path).read_text)
```

That lets the agent loop stay async without introducing extra dependencies.

## The implementation

### Step 1: Build the definition

Initialize `self._definition` with a `ToolDefinition` named `read`.

### Step 2: Implement `definition`

Return the stored definition object.

### Step 3: Implement `call()`

The logic is:

1. extract `path` from `args`
2. validate that it is a string
3. read the file with `asyncio.to_thread(Path(path).read_text)`
4. return the contents

For argument handling, a common pattern is:

```python
path = args.get("path") if isinstance(args, dict) else None
if not isinstance(path, str):
    raise ValueError("missing 'path' argument")
```

For file errors, raise a helpful message that includes the path:

```python
raise RuntimeError(f"failed to read '{path}'") from exc
```

## Running the tests

Run the Chapter 2 tests:

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src uv run python -m pytest tests/test_ch2.py
```

### What the tests verify

- the tool definition is named `read`
- `path` is required in the schema
- reading a normal file returns its contents
- missing files raise an error
- missing arguments raise an error

## Recap

You built your first tool and learned the core tool pattern:

1. define a `ToolDefinition`
2. expose it through `definition`
3. implement the real behavior in `call()`

## What's next

In [Chapter 3: Single Turn](./ch03-single-turn.md) you will connect the
provider and tools for the first time and handle one full tool-calling round.
