# Chapter 4: More Tools

Now you fill out the rest of the toolset:

- `BashTool`
- `WriteTool`
- `EditTool`

All three live in `mini-claw-code-starter-py/src/mini_claw_code_starter_py/tools/`.

## BashTool

Use `asyncio.create_subprocess_exec()` to run `bash -lc <command>`:

```python
process = await asyncio.create_subprocess_exec(
    "bash",
    "-lc",
    command,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await process.communicate()
```

Return stdout first, then stderr prefixed with `stderr: `. If both are empty,
return `(no output)`.

## WriteTool

Use `Path(path).parent.mkdir(parents=True, exist_ok=True)` before writing.
Again, wrap filesystem work with `asyncio.to_thread()`.

Return a confirmation string like:

```python
return f"wrote {path}"
```

## EditTool

This tool is intentionally strict:

1. read the file
2. count occurrences of `old_string`
3. reject `0` matches
4. reject more than `1` match
5. replace exactly one occurrence

That exact-match rule prevents ambiguous edits.

## Run the tests

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src python -m pytest tests/test_ch4.py
```
