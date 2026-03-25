# Chapter 10: Streaming

`Provider.chat()` waits for a full response. Streaming exposes tokens as they
arrive.

The Python port adds:

- `StreamEvent` variants
- `StreamAccumulator`
- `parse_sse_line()`
- `StreamProvider`
- `MockStreamProvider`
- `StreamingAgent`

## Event model

The Python version uses small dataclasses:

```python
TextDelta("Hel")
ToolCallStart(index=0, id="call_1", name="read")
ToolCallDelta(index=0, arguments='{"path": "README.md"}')
StreamDone()
```

`StreamAccumulator` collects those events and reconstructs the final
`AssistantTurn`.

## Parsing SSE

OpenAI-compatible streaming responses arrive line-by-line:

```text
data: {"choices":[{"delta":{"content":"Hello"}}]}
data: [DONE]
```

`parse_sse_line()` turns each line into zero or more stream events. The
accumulator does the rest.

## Streaming agent loop

`StreamingAgent` mirrors `SimpleAgent`, but it also forwards `TextDelta`
events into an `asyncio.Queue` for the UI.

That keeps the design layered:

- provider -> raw stream events
- accumulator -> complete assistant turn
- agent -> tool loop
- UI -> user-facing event rendering
