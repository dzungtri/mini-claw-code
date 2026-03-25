# Chapter 2: Your First Tool

Your first tool is `ReadTool`: it receives a file path and returns the file
contents.

Open `mini-claw-code-starter-py/src/mini_claw_code_starter_py/tools/read.py`.

## Goal

Implement `ReadTool` so that:

1. it declares a `ToolDefinition` named `read`
2. it requires one `path` string parameter
3. it reads the target file asynchronously
4. it raises helpful errors for missing arguments or missing files

## Tool shape in Python

Every tool follows the same structure:

```python
class ReadTool:
    @property
    def definition(self) -> ToolDefinition:
        ...

    async def call(self, args: Any) -> str:
        ...
```

The schema uses the same builder pattern as the Rust book:

```python
ToolDefinition.new("read", "Read the contents of a file.").param(
    "path", "string", "The file path to read", True
)
```

## Async file I/O

Python's standard library does not expose true async filesystem APIs, so this
book uses `asyncio.to_thread()`:

```python
content = await asyncio.to_thread(Path(path).read_text)
```

That keeps the async agent loop responsive while the file operation runs in a
worker thread.

## Run the tests

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src python -m pytest tests/test_ch2.py
```

Once `ReadTool` works, the rest of the tool chapter is mostly repetition.
