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

## The Smallest Good Shape

The envelope should include:

- `message_id`
- `source`
- `target_agent`
- `thread_key`
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
  "kind": "user_message",
  "content": "Build feature A",
  "metadata": {},
  "created_at": "2026-03-28T12:00:00Z"
}
```

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

The key contract is:

```python
await bus.publish(envelope)
envelope = await bus.consume()
```

That is enough to let the rest of the OS take shape cleanly.
