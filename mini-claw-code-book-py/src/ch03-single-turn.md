# Chapter 3: Single Turn

Before building the full agent loop, handle the raw protocol directly.

Open `mini-claw-code-starter-py/src/mini_claw_code_starter_py/agent.py` and
implement `single_turn()`.

## Goal

`single_turn()` should:

1. build a message history starting with the user prompt
2. call the provider once
3. inspect `turn.stop_reason`
4. either return text immediately or execute one round of tool calls
5. call the provider a second time when tool results are available

## The key idea

Do not infer behavior from `tool_calls` being empty or not. Match on the
explicit protocol signal:

```python
if turn.stop_reason is StopReason.STOP:
    return turn.text or ""
```

Otherwise the model is asking for tools.

## Tool execution rule

Never crash the loop on tool failure. Convert tool failures into strings and
send them back as tool results:

```python
try:
    content = await tool.call(call.arguments)
except Exception as exc:
    content = f"error: {exc}"
```

That makes the agent resilient. The model can recover instead of losing the
whole conversation.

## Run the tests

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src python -m pytest tests/test_ch3.py
```
