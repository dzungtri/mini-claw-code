# Chapter 1: Core Types

In this chapter you learn the protocol that connects the model, the agent
loop, and the tools.

Open `mini-claw-code-starter-py/src/mini_claw_code_starter_py/types.py`.

The important types are:

- `ToolDefinition` — a tool schema that the model can inspect
- `ToolCall` — one tool request emitted by the model
- `AssistantTurn` — the model output for a single provider call
- `StopReason` — either `STOP` or `TOOL_USE`
- `Message` — the conversation history
- `Provider` — the async interface for any model backend
- `ToolSet` — a name-indexed collection of tools

## Goal

Implement `MockProvider` in `mini-claw-code-starter-py/src/mini_claw_code_starter_py/mock.py`
so that each `chat()` call returns the next canned `AssistantTurn`.

## Python version of the protocol

Rust needed enums, traits, and interior mutability. Python is simpler:

```python
@dataclass(slots=True)
class AssistantTurn:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: StopReason
```

`Message` is represented as one dataclass with helper constructors:

```python
Message.system("...")
Message.user("read README.md")
Message.assistant(turn)
Message.tool_result("call_1", "file contents")
```

The provider interface is just an async protocol:

```python
class Provider(Protocol):
    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        ...
```

## Implementing `MockProvider`

Use `collections.deque` for FIFO behavior:

```python
responses = deque([first_turn, second_turn])
turn = responses.popleft()
```

Your implementation only needs two pieces:

1. `new()` should return a `MockProvider` storing the deque.
2. `chat()` should `popleft()` the next response or raise an error when empty.

## Run the tests

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src python -m pytest tests/test_ch1.py
```

If those tests pass, your protocol foundation is ready.
