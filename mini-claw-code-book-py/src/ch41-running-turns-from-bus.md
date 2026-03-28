# Chapter 41: Running Harness Turns From the Bus

At this point, the OS has:

- message envelopes
- a bus
- an agent registry
- session routing

Now it needs one more thing:

a runner that can turn one bus message into one harness turn.

## The Goal

We want a clean runner contract:

1. receive one envelope
2. resolve target agent
3. resolve session
4. build a harness runtime from the registry definition
5. run one turn
6. stream events
7. publish final outputs
8. emit trace and log state for operators

## Requirements

The runner should:

- work for the current CLI path first
- preserve session continuity
- stream the same runtime events we already have
- remain compatible with `make cli`
- assign or propagate trace identifiers
- support later cancellation hooks

For the first implementation, prefer:

- build a fresh harness runtime per turn
- restore durable session state into it

That is simpler and safer than introducing long-lived runtime caches too early.

It does **not** need:

- horizontal scaling
- multiple worker pools
- distributed schedulers

## Architecture

The first version should include:

- `TurnRunner`
- `RunnerContext`
- `RunnerResult`
- run tracing hooks

The key contract is:

```python
result = await runner.run(envelope)
```

That call should stay small.

The runner is an OS component.

The harness remains the execution engine inside it.

That means the runner becomes the best place to correlate:

- one inbound envelope
- one target agent
- one session
- one run id
- one trace id
