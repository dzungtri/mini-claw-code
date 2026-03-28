# Chapter 37: Message Envelopes and the Bus

Now that we have defined the Agent OS boundary, the first thing we need is a common message envelope.

Without that, every channel and every background service will invent its own message shape.

That becomes unmaintainable very quickly.

## The Goal

We want one normalized message format that can represent:

- a user turn from the CLI
- a user turn from Telegram
- a message from a dashboard
- a scheduled cron turn
- a heartbeat turn
- a peer-agent request

That envelope should be transport-neutral.

For most user-facing channels, the default target should be:

- `superagent`

Direct targeting of peer agents should be treated as:

- an advanced routing feature
- or an internal/system envelope

For the first implementation, we should keep the scope narrow:

- one local in-process bus
- one typed envelope model
- one typed event envelope model
- no distributed transport
- no persistence

That is enough to support the next chapters cleanly.

## The Smallest Good Shape

The envelope should include:

- `message_id`
- `source`
- `target_agent`
- `thread_key`
- `trace_id`
- `parent_run_id`
- `kind`
- `content`
- `metadata`
- `created_at`

The important idea is that this is an **OS envelope**, not a raw chat message.

It is allowed to carry routing and tracing state that should never appear directly in the LLM prompt.

Example:

```json
{
  "message_id": "msg_001",
  "source": "cli",
  "target_agent": "superagent",
  "thread_key": "cli:local",
  "trace_id": "trace_abc123",
  "parent_run_id": null,
  "kind": "user_message",
  "content": "Build feature A",
  "metadata": {},
  "created_at": "2026-03-28T12:00:00Z"
}
```

In the first OS slice, `target_agent` should usually be `superagent`.

Later, the OS can support:

- explicit peer-agent routing
- team-lead routing
- background service routing

## Field Semantics

These fields need stable meanings from the start.

### `message_id`

A unique id for this envelope.

This is useful for:

- logging
- debugging
- audit trails

### `source`

Where the envelope came from.

Examples:

- `cli`
- `telegram`
- `dashboard`
- `cron`
- `heartbeat`

### `target_agent`

The hosted agent that should receive this turn.

In the first version, this will usually be `superagent`.

### `thread_key`

The external conversation identity.

Examples:

- `cli:local`
- `telegram:123456`

This is not the same as `session_id`.

### `trace_id`

A correlation id shared by related envelopes, runs, and later events.

The first version does not need a distributed tracing system.

But it should still carry a stable local trace id.

### `parent_run_id`

Optional linkage to the run that created this envelope.

This becomes important later for:

- peer-agent requests
- background follow-up work
- operator inspection

### `kind`

The semantic type of work.

The first version should keep this small.

Recommended initial kinds:

- `user_message`
- `system_message`
- `background_message`

### `content`

The main textual content for the turn.

For the first version, keep this as text.

Do not introduce multimodal blocks here yet.

### `metadata`

Transport-specific or system-specific extras.

Examples:

- chat id
- original channel user id
- scheduler label

### `created_at`

Creation timestamp for the envelope.

This is important for:

- logs
- ordering diagnostics
- later monitoring views

## Why A Bus Matters

The bus exists to decouple:

- message producers
- message consumers

Producers:

- CLI
- dashboard
- Telegram
- cron
- heartbeat

Consumers:

- session router
- runner
- outbound dispatch
- audit/logging

The bus does not do reasoning.

It only carries normalized work.

That means the bus should not:

- build prompts
- restore sessions
- call the model
- execute tools

## Requirements

The first bus should:

- accept local in-process messages
- support inbound and outbound queues
- preserve ordering within one thread
- allow different sources to share one pipeline
- remain simple enough for the tutorial
- preserve `target_agent` and `thread_key` without transport-specific rewriting
- preserve correlation fields such as `trace_id`

It should also:

- expose one inbound queue and one outbound queue
- preserve FIFO ordering within each queue
- be easy to test without threads or sockets

It does **not** need:

- distributed delivery
- durable replay
- exactly-once guarantees

Those can come later.

## Event Envelopes

The bus should also support OS-level events.

That does **not** mean replacing the harness event system.

It means adding one OS wrapper shape for messages like:

- run started
- run finished
- outbound user response
- operator event

So for this chapter, we should also define:

- `EventEnvelope`

with fields similar to:

- `event_id`
- `trace_id`
- `kind`
- `payload`
- `created_at`

This gives the OS a place to move non-chat events without polluting the user message envelope.

## Architecture

The first version should include:

- `Envelope`
- `InboundBus`
- `OutboundBus`
- `EventEnvelope`
- trace-aware envelopes

For the codebase, the smallest clean module shape is:

```text
mini_claw_code_py/os/
  __init__.py
  envelopes.py
  bus.py
```

In this project, the first implementation uses:

- [envelopes.py](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/envelopes.py)
- [bus.py](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/bus.py)

The concrete names are:

- `MessageEnvelope`
- `EventEnvelope`
- `MessageBus`

That keeps the harness code flat while giving the OS layer a real home.

## What We Will Actually Implement First

The first implementation slice should include:

1. typed dataclasses for envelopes
2. id and timestamp helpers
3. local async queues for:
   - inbound envelopes
   - outbound envelopes
   - event envelopes
4. simple `publish_*` and `consume_*` methods

It should **not** include yet:

- agent registry integration
- session routing
- runner logic
- gateway logic

Those belong to the next chapters.

## The First Concrete API

The first implementation keeps the API intentionally small:

```python
envelope = MessageEnvelope(
    source="cli",
    target_agent="superagent",
    thread_key="cli:local",
    kind="user_message",
    content="Build feature A",
)

await bus.publish_inbound(envelope)
received = await bus.consume_inbound()
```

And for OS-level events:

```python
event = EventEnvelope(
    kind="run_started",
    payload={"run_id": "run_001"},
    trace_id=envelope.trace_id,
)

await bus.publish_event(event)
```

This is enough for later chapters to layer on:

- session routing
- runner state
- operator views
- background services

The key contract is:

```python
await bus.publish(envelope)
envelope = await bus.consume()
```

That is enough to let the rest of the OS take shape cleanly.

## Why This Chapter Comes First

If we skip envelopes and the bus, later chapters will be forced to invent ad hoc message shapes.

That would damage the whole design.

So this chapter is intentionally small.

But it is foundational.
