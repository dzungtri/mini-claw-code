# Overview

This book is the Python rewrite of the original Rust tutorial. The goal is the
same: build a small coding agent from first principles, one chapter at a time.

The repository is split into three Python projects:

- `mini-claw-code-py` — the complete reference implementation
- `mini-claw-code-starter-py` — the learner version with `NotImplementedError`
  exercises
- `mini-claw-code-book-py` — this mdBook source

The teaching arc stays the same:

1. Define the protocol types.
2. Build tools.
3. Handle one provider turn.
4. Wrap that protocol in an agent loop.
5. Connect the loop to a real HTTP provider and CLI.

The biggest language shift from the Rust book is that Python does not need
ownership rules, `async_trait`, or `Box<dyn Tool>`. Instead, we use:

- `dataclasses` for the protocol values
- `async def` for every provider and tool entry point
- simple protocols and duck typing for `Provider` and `Tool`
- `asyncio` for process execution, queues, streaming, and the REPL

Use the starter project if you want the hands-on path:

```bash
cd mini-claw-code-starter-py
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
PYTHONPATH=src uv run python -m pytest tests/test_ch1.py
```

Use the reference implementation when you want to compare your work or jump
ahead:

```bash
cd mini-claw-code-py
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
PYTHONPATH=src uv run python -m pytest
```
