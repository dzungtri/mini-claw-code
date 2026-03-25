# Chapter 7: A Simple CLI

Now wire the provider and tools into a real command-line loop.

Open `mini-claw-code-starter-py/examples/chat.py`.

## Goal

Build a CLI that:

1. keeps conversation history across turns
2. reads input until EOF
3. pushes `Message.user(...)` before each agent call
4. prints the final text
5. stays alive on per-request errors

## History-based chat

`run()` creates a new history for every prompt. `chat()` takes an existing
history so the model can remember prior context.

That means the REPL looks like this:

```python
history.append(Message.user(prompt))
text = await agent.chat(history)
print(text)
```

## Minimal CLI shape

```python
while True:
    prompt = input("> ").strip()
    if not prompt:
        continue
    history.append(Message.user(prompt))
    print("    thinking...", end="", flush=True)
    text = await agent.chat(history)
```

## Run everything

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src uv run python -m pytest
```

Then try the reference example:

```bash
cd ../mini-claw-code-py
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
PYTHONPATH=src uv run python examples/chat.py
```
