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

## Requirements

The first bus should:

- accept local in-process messages
- support inbound and outbound queues
- preserve ordering within one thread
- allow different sources to share one pipeline
- remain simple enough for the tutorial
- preserve `target_agent` and `thread_key` without transport-specific rewriting
- preserve correlation fields such as `trace_id`

It does **not** need:

- distributed delivery
- durable replay
- exactly-once guarantees

Those can come later.

## Architecture

The first version should include:

- `Envelope`
- `InboundBus`
- `OutboundBus`
- `EventEnvelope`
- trace-aware envelopes

The key contract is:

```python
await bus.publish(envelope)
envelope = await bus.consume()
```

That is enough to let the rest of the OS take shape cleanly.
