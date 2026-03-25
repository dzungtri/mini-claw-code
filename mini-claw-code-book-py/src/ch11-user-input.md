# Chapter 11: User Input

Real agents should not guess when they need clarification. They should ask.

The Python port adds:

- `InputHandler`
- `AskTool`
- `CliInputHandler`
- `ChannelInputHandler`
- `MockInputHandler`

## Tool schema

`AskTool` exposes:

- `question` — required string
- `options` — optional array of strings

That means the model can either ask a free-text question or present explicit
choices.

## Handler abstraction

Different frontends need different input paths:

- CLI -> call `input()` in a thread
- TUI -> send a request object through an `asyncio.Queue`
- tests -> pop canned answers from a `deque`

The interface stays the same:

```python
class InputHandler(Protocol):
    async def ask(self, question: str, options: Sequence[str]) -> str:
        ...
```

That keeps `AskTool` reusable across every interface.
