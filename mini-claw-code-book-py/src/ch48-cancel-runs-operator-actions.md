# Chapter 48: Cancelling Runs and Operator Actions

By Chapter 47, we can already **see** the system.

That is necessary, but it is not enough.

An operator console becomes real only when it can also **change** system state in controlled ways.

The first operator action should be:

- `cancel run <id>`

This chapter defines how cancellation should work in the Agent OS before we implement it.

## Why Cancel Comes First

Among all operator actions, cancellation is the best first control feature because it touches the most important runtime boundaries:

- live run state
- the runner
- the harness turn loop
- monitoring surfaces
- audit trails
- operator permissions

It also forces us to answer an important production question:

what does it mean to stop agent work safely?

That makes `cancel run <id>` the right first operator command.

## The Product Requirement

From the operator's point of view, cancellation should mean:

1. identify an active run
2. request that it stop
3. see its status change quickly
4. know whether it actually stopped cleanly
5. know what partial state was left behind

That means the system must support both:

- **control**
- **traceability**

The operator should never wonder:

- was the command accepted?
- is the run still active?
- did the stop actually happen?
- was the run already finished?

## Control Action Vocabulary

Before designing implementation, we should define the terms clearly.

### Cancel

A request to stop a run as soon as the runtime reaches a safe interruption point.

This is the first action we want.

### Kill

A hard forced stop of the process or worker without waiting for clean runtime boundaries.

This is **not** the first action we want.

It is more dangerous and belongs later.

### Pause

A request to stop accepting new work while keeping state ready to resume.

This also belongs later.

### Drain

Allow current work to finish but stop scheduling new work.

This belongs later too.

So for the first implementation we should support only:

- `cancel`

## The Core Design Rule

The first cancellation mechanism should be:

- cooperative
- explicit
- observable
- auditable

It should **not** start as:

- raw process kill
- abrupt thread interruption
- filesystem-level force stop

That means cancellation should flow through runtime state, not around it.

## Cooperative Cancellation

The simplest safe model is:

1. operator requests cancel
2. the OS records a cancellation request for a run
3. the runner notices the request
4. the runner asks the active harness loop to stop at the next safe point
5. the run finishes with status `cancelled`

This is the right first design because it works with the runtime we already have:

- a turn loop
- event queues
- tool-call boundaries
- subagent boundaries

It does not require unsafe thread termination.

## Safe Interruption Points

The runtime should only honor cancellation at points where state can still be written cleanly.

The best first safe points are:

- before the next model call
- after a model call finishes
- before a tool starts
- after a tool finishes
- before launching a subagent
- after a subagent finishes

This is a very important rule.

If cancellation is checked only at these boundaries, then:

- session state can still be saved
- run status can still be updated
- audit entries can still be written
- the operator can trust the result

## What We Should Not Promise Yet

For the first implementation, cancellation should **not** promise:

- interrupting a shell command in the middle
- interrupting a remote MCP call in the middle
- killing a child Python task at arbitrary bytecode points
- rolling back partial file changes

That would make the first implementation more dangerous and much more complex.

So the first operator contract should be:

> cancellation is best-effort at safe runtime boundaries, not arbitrary hard-stop preemption.

## Run State Model

To support cancellation, a run needs more than a final `status`.

We need to distinguish:

- `running`
- `cancelling`
- `cancelled`
- `completed`
- `failed`

The key new state is:

- `cancelling`

That means:

- the operator request has been accepted
- the runtime has not yet stopped

This gives the operator an honest view of the system.

Without `cancelling`, the dashboard would have to choose between two bad options:

- lie and show `running`
- or lie and show `cancelled` before the run actually stopped

## Recommended Status Transition

The lifecycle should look like this:

```text
running
  -> cancelling
  -> cancelled
```

And the other existing transitions still remain:

```text
running -> completed
running -> failed
```

The important rule is:

`cancelled` should only be written after the runner has actually stopped the run.

## Cancellation Flow

The first runtime design should look like this:

```text
operator console
    |
    v
OperatorService.cancel_run(run_id)
    |
    v
RunControlStore marks run as cancelling
    |
    v
TurnRunner observes cancel request
    |
    v
HarnessAgent stops at next safe point
    |
    v
RunStore writes status=cancelled
    |
    v
operator dashboard refreshes
```

This is the right shape because it keeps a clean separation:

- operator console submits commands
- control state is stored centrally
- runner enforces the command
- run store records the outcome

## The New Backend Piece

To support this cleanly, the OS should add a small control-state store.

For the first slice, that can be a flat file-backed store like:

- `RunControlStore`

It only needs to track a few things:

- `run_id`
- requested action
- requested at
- requested by
- optional reason
- resolved at
- resolved result

This is intentionally separate from `RunStore`.

Why?

Because:

- `RunStore` records what happened
- `RunControlStore` records what operators asked the system to do

That separation is much better for monitoring and audit.

## Operator Command Model

The first command model should stay small and explicit.

For example:

```text
/cancel run <run_id>
```

or internally:

```python
OperatorCommand(
    kind="cancel_run",
    run_id="run_123",
    actor="operator",
    reason="manual stop",
)
```

The UI syntax can stay simple, but the backend should still think in terms of a real command object.

That will make later transports easier:

- TUI
- web
- HTTP
- gRPC

## Audit Requirements

Every operator action must be auditable.

That means cancellation must record:

- who requested it
- when
- for which run
- whether the run was active
- whether the request was accepted
- when the run actually stopped
- what final state was written

This is not optional.

An operator console without auditability becomes untrustworthy very quickly.

## Monitoring Requirements

Once cancellation exists, the dashboard should make it visible.

At minimum, the operator surface should show:

- current status: `running`, `cancelling`, `cancelled`
- when cancellation was requested
- whether the run is still consuming turns or tokens
- final token and cost totals once cancellation completes

This is important because cancelled work still has cost.

The operator should be able to see:

- how much cost had already been consumed before the stop completed

## Subagents and Cancellation

The first implementation should define a simple rule:

- cancelling a parent run cancels the parent run
- any child subagents launched under that run should also stop at their next safe point

This is a tree-shaped cancellation rule.

The operator should not need to cancel:

- parent
- then child
- then grandchild

The system should propagate that stop intent downward.

For the first slice, it is acceptable if this propagation is only best-effort and only for local child execution.

## UI and UX

The operator console should expose cancellation in two ways.

### 1. Slash Command

At the bottom command line:

```text
/cancel run run_123
```

This is the easiest first path.

### 2. Inspect Screen Action

In the later inspect-run view, the operator should also see something like:

```text
[c] cancel run
```

But the slash command is enough for the first milestone.

## Example Dashboard Behavior

Before cancellation:

```text
Runs
- run_123: superagent running turns=7 tokens=18240 cost=$0.093000 ctx=71%
```

After request accepted:

```text
Runs
- run_123: superagent cancelling turns=7 tokens=18240 cost=$0.093000 ctx=71%
```

After stop completes:

```text
Runs
- run_123: superagent cancelled turns=8 tokens=19320 cost=$0.098400 ctx=73%
```

The operator can now see:

- the state transition
- the final cost
- that the stop was real

## What The First Implementation Should Build

The first implementation after this chapter should do:

1. add `cancelling` and `cancelled` handling to run state
2. add `RunControlStore`
3. add `OperatorService.cancel_run(run_id)`
4. make the runner check for cancellation at safe points
5. add `/cancel run <id>` to `make ops`
6. record audit and operator-visible status transitions

That is enough to make the first operator action real.

## What Can Wait

We should **not** expand scope too early.

These belong later:

- `pause`
- `drain`
- `kill`
- restart
- reroute while active
- multi-operator permission roles
- remote distributed cancellation across ACP workers

Those are all valid production features, but they should come after we prove one clean operator action end to end.

## Main Design Rule

The first operator action should not be flashy.

It should be:

- safe
- explicit
- visible
- auditable

That is exactly why `cancel run <id>` should come first.
