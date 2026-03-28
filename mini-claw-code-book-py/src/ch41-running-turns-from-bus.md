# Chapter 41: Running Harness Turns From the Bus

By Chapter 40, the OS can:

- receive envelopes
- know which hosted agents exist
- route a front-door thread to a harness session

Now it needs one more piece:

a runner.

The runner is the OS component that turns:

- one inbound envelope

into:

- one harness turn
- one persisted session update
- one run record
- one outbound envelope

## What We Are Building

The first runner should stay local and small.

It should:

1. receive one `MessageEnvelope`
2. resolve the hosted agent
3. resolve the routed session
4. build a fresh `HarnessAgent`
5. restore durable session state
6. append the inbound message
7. execute one turn
8. persist session state
9. persist a run record
10. return one outbound envelope

That is enough to make the OS path real.

## Why A Runner Is Necessary

Without a runner, the OS still has two separate worlds:

- the OS world of envelopes, routes, and agent identities
- the harness world of messages, tools, and model turns

The runner is the bridge.

It is where the OS calls into the harness.

## Fresh Runtime Per Turn

The first runner should build a fresh harness runtime on every turn.

That means:

- look up the hosted agent definition
- build a new `HarnessAgent` from the factory
- restore saved session state into it

This is the right first tradeoff.

It is simpler than long-lived runtime pools, and it matches the session design we already built.

## The First Concrete Types

The first slice should introduce:

- `RunnerContext`
- `RunnerResult`
- `TurnRunner`

The key call stays small:

```python
result = await runner.run(envelope)
```

## `RunnerContext`

The context should capture the important OS correlation state for the turn:

- inbound envelope
- resolved route
- resolved session
- started run record

That gives the caller one stable object to inspect.

## `RunnerResult`

The result should return:

- the context
- the built `HarnessAgent`
- the updated history
- the final reply text
- the outbound envelope

Returning the built agent matters for the CLI.

The CLI still wants to inspect:

- todos
- artifacts
- MCP state
- audit state

after the turn finishes.

So the runner should not hide the built harness runtime.

## Run Records

The runner should start a run record at the beginning of execution and finish it at the end.

For the first slice:

- `task_id` may be missing

Why:

The front-door `superagent` path exists before we have full goal-to-task orchestration.

That should not stop us from recording traceable runs.

So the first run record may describe:

- a front-door conversation turn

without already being attached to a formal team task.

Later chapters can connect those more tightly.

## Current Front-Door Refinement

The next useful refinement for the real `make cli` path is:

- if the inbound envelope does not already specify a `task_id`
- and the routed session has no work binding yet
- create one goal and one front-door task for that session

Then the runner can attach later runs in that session to the bound task.

This is a good first compromise:

- the runner stays small
- the front door becomes real OS work
- we still avoid premature full planning/orchestration logic

## Event Streaming

The first runner should stream the same harness runtime events the CLI already knows how to render.

That means the runner should not invent a second event language for basic turn output.

For the first slice:

- the runner passes through harness runtime events
- and optionally publishes OS event envelopes if a bus is attached

That keeps the user surface stable while the OS grows underneath it.

## Bus Publishing

The first runner should support an optional `MessageBus`.

If a bus is present, the runner should publish:

- `run_started`
- `run_finished`
- `outbound_message`

If no bus is present, the runner should still work.

That is important because the first real consumer is the local CLI, not a distributed worker system.

## Where Usage And Cost Belong

The runner is also the right place to finalize usage accounting.

Why:

- it already correlates one inbound envelope to one concrete run
- it sees the restored session, the built harness, and the final turn result
- it is the place that writes the durable run record

So the runner should compute and persist:

- prompt tokens
- completion tokens
- total tokens
- provider / model identity
- pricing key
- estimated input cost
- estimated output cost
- estimated total cost

The operator console should only display and aggregate those numbers.

It should not recalculate billing logic by itself.

## Current Local Implementation

Today, the runner already writes local OS state that `make ops` can read:

- run records in `.mini-claw/os/runs.json`
- route bindings in `.mini-claw/os/routes.json`
- session state in `.mini-claw/sessions/...`
- control requests in `.mini-claw/os/run_controls.json`

So the current local operator path is:

```text
make cli -> TurnRunner -> .mini-claw state
make ops -> OperatorService -> .mini-claw state
```

This is a file-backed control plane.

It works well for:

- one machine
- many terminals
- one shared project root

It is not yet a networked control plane.

The important implementation detail is that we now support both local execution entries through the same runner:

- direct local path:
  - `TurnRunner.run(envelope)`
- bus-mediated local path:
  - `MessageBus.publish_inbound(...)`
  - `TurnRunner.run_from_bus()`

That keeps the execution spine stable while we add gateways and remote transports later.

## Message Conversion

The runner needs one small translation step:

- inbound `MessageEnvelope`
- to harness `Message`

For the first slice:

- `user_message` becomes `Message.user(...)`
- `system_message` becomes `Message.system(...)`
- `background_message` can follow the user path until later chapters need something richer

That is enough for the early OS path.

## CLI First

The current CLI should start using the runner for normal execution turns.

That means:

- prompt becomes inbound envelope
- runner executes the turn
- CLI renders the same event stream
- current session and route are updated from the runner result

For this chapter, plan mode can stay on the direct harness path.

That keeps the first runner slice small and avoids mixing bus execution with plan approval flow too early.

## What We Intentionally Skip

The first runner does **not** need:

- worker pools
- distributed schedulers
- remote execution
- cancellation tokens
- task retries
- concurrency controls

Those belong later.

## Main Design Rule

Keep the runner as a wrapper around the harness, not a second agent framework.

The runner should:

- correlate
- restore
- execute
- persist
- publish

It should not:

- own prompt design
- own tool definitions
- own model behavior

Those still belong to the harness.

## Implementation Target

The first concrete slice should introduce:

- `TurnRunner`
- `RunnerContext`
- `RunnerResult`

And it should move the CLI execution path to:

```text
prompt -> MessageEnvelope -> TurnRunner -> HarnessAgent -> RunnerResult
```

That is the point where the Agent OS stops being only design and starts becoming the real runtime path.
