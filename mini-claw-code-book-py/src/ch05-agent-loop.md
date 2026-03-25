# Chapter 5: Your First Agent SDK!

This chapter is the payoff: wrap the single-turn protocol in a loop and you
have an agent.

Open `mini-claw-code-starter-py/src/mini_claw_code_starter_py/agent.py` and
implement `SimpleAgent`.

## Goal

`SimpleAgent` should:

1. store a provider and a `ToolSet`
2. let callers register tools with `.tool(...)`
3. keep looping until the provider returns `StopReason.STOP`

## Python design

The constructor is ordinary Python:

```python
class SimpleAgent:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.tools = ToolSet()
```

The builder is still fluent:

```python
agent = (
    SimpleAgent(provider)
    .tool(BashTool())
    .tool(ReadTool())
    .tool(WriteTool())
    .tool(EditTool())
)
```

## The loop

The logic is just Chapter 3 repeated:

```python
while True:
    turn = await self.provider.chat(messages, defs)
    if turn.stop_reason is StopReason.STOP:
        ...
    else:
        ...
```

Each `TOOL_USE` turn becomes:

1. execute all requested tools
2. append `Message.assistant(turn)`
3. append `Message.tool_result(...)` for each result
4. continue the loop

## Run the tests

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src python -m pytest tests/test_ch5.py
```
