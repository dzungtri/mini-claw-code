# Chapter 46: Traceability, Monitoring, and Operator Controls

An Agent OS is not complete if it cannot be observed and controlled.

By this point, the system can already:

- host agents
- route sessions
- run turns
- drive background turns
- expose an operator console

But until this chapter, the operator mostly saw summaries:

- runs
- sessions
- routes
- totals

That is useful, but still incomplete.

We also need the OS to answer:

- what happened inside a run?
- in what order did it happen?
- which events belong to the same trace?

This chapter implements the first real timeline layer.

## The Core Requirement

Everything important in the OS should be traceable.

At minimum that includes:

- envelopes
- runs
- sessions
- tool calls
- subagent updates
- context compaction
- approvals
- usage signals
- outbound replies

If something changes the system, an operator should be able to answer:

- what happened?
- when did it happen?
- which run did it belong to?
- which session did it belong to?
- which trace did it belong to?
- which agent produced it?

## The Three Pillars

### 1. Tracing

Tracing answers:

- what execution path did this run follow?

At the current OS level, that means:

- envelope
- runner
- harness turn
- tool and subagent activity
- final outbound message

The current identifiers remain:

- `trace_id`
- `run_id`
- `task_id`
- `goal_id`
- `session_id`
- `thread_key`
- `target_agent`

But now we also persist a timeline of events under those identifiers.

### 2. Monitoring

Monitoring answers:

- what is the current health and state of the system?

That includes:

- active and completed runs
- tokens
- cost
- context pressure
- agent and team totals
- alerts

This was already partially real in the operator dashboard.

This chapter makes the monitoring layer deeper by giving each run a visible event trail.

### 3. Operator Controls

Operator controls answer:

- what can a human do when the system is unhealthy or unsafe?

We already have:

- run inspection
- run cancellation

This chapter improves inspection by making it timeline-backed instead of summary-only.

## What We Implement

The first concrete observability slice adds:

- `OperatorEventRecord`
- `OperatorEventStore`
- append-only JSONL persistence
- per-run event lookup
- operator-service event inspection
- timeline rendering in `inspect run`

The implementation lives in:

- [`event_log.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/event_log.py)
- [`runner.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/runner.py)
- [`operator.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/operator.py)
- [`ops/app.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/ops/app.py)

## Why We Use JSONL

The event log uses:

- one JSON object per line

stored at:

- `.mini-claw/os/operator_events.jsonl`

This is a good first production choice because it is:

- append-friendly
- easy to inspect with normal shell tools
- easy to parse in tests
- closer to real log streams than a big rewritten JSON array

It also keeps the code simple.

## Operator Event Model

Each event record stores:

- `event_id`
- `created_at`
- `kind`
- `trace_id`
- `run_id`
- `session_id`
- `target_agent`
- `payload`

That is intentionally boring and explicit.

This chapter does not try to build a complex tracing backend.

It just ensures that useful execution breadcrumbs become durable OS state.

## What Gets Recorded Now

### OS-level run events

The runner records:

- `run_started`
- `outbound_message`
- `run_finished`

These are persisted even if no operator console is open.

### Harness-derived events

The runner also maps selected harness events into operator events, including:

- `agent.tool_call`
- `agent.subagent`
- `agent.context_compaction`
- `agent.approval`
- `agent.usage`
- `agent.todos`
- `agent.memory`
- `agent.artifacts`

Not every internal event needs to become a durable operator event.

The important rule is:

- persist what helps operators explain behavior

## Runtime Path

The current path looks like this:

```text
MessageEnvelope
  -> TurnRunner.run(...)
  -> persist run_started
  -> execute harness turn
  -> relay structured harness events
  -> persist mapped operator events
  -> persist outbound_message
  -> persist run_finished
```

That means the operator timeline is built from the same real runtime path that produces the work.

It is not a fake dashboard-only summary.

## Inspecting a Run

The operator service now exposes:

- `inspect_run(run_id)`
- `inspect_run_events(run_id)`

And the operator console uses both when the user inspects a run.

So `make ops` can now show:

- run metadata
- token and cost usage
- context pressure
- a short timeline of what happened during that run

This makes the detail view much closer to a real task-manager style inspection panel.

## Why This Matters

Without a timeline, operators can see:

- a run existed
- it finished or failed
- it consumed some tokens

But they still cannot see:

- whether it called tools
- whether it delegated subagents
- whether it compacted context
- whether an approval gate triggered

The event timeline closes that gap.

## Current Monitoring Boundary

The system is still in local-mode monitoring:

- file-backed
- same project root
- timer-refreshed operator console

That is okay for this stage.

The key thing is that the traceability model is now explicit and durable.

Later, the same event model can be pushed into:

- a central control plane
- streaming operator APIs
- multi-node aggregation

## Tokens and Money

The design rule stays the same:

- token and money calculation belong in the execution core
- monitoring only displays and aggregates them

That is why the runner still owns:

- token totals
- pricing key
- estimated input cost
- estimated output cost
- estimated total cost

The operator layer reads those values and correlates them with run and event data.

## Testing Focus

The Chapter 46 tests protect:

1. append-only event persistence
2. filtering events by run id
3. runner integration
4. operator-service event lookup
5. run detail rendering through the operator console

Tests live in:

- [`test_ch46.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/tests/test_ch46.py)
- [`test_ch47.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/tests/test_ch47.py)

## Result

After this chapter, the Agent OS has a real traceability backbone:

- durable run metadata
- durable operator event timeline
- per-run inspection
- token and cost visibility
- safer operator debugging

That is the minimum shape of a real observable Agent OS.
