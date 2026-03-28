# Chapter 46: Traceability, Monitoring, and Operator Controls

An Agent OS is not complete if it cannot be observed and controlled.

This is one of the most important requirements in the whole system.

If we can run:

- many agents
- many teams
- many goals
- many sessions
- many background services

then we also need to be able to:

- inspect what is happening
- understand why it happened
- find what is stuck
- stop or cancel unsafe work

In other words:

an Agent OS needs something like a task manager.

## The Core Requirement

Everything important in the OS should be traceable.

That includes:

- envelopes
- goals
- tasks
- runs
- sessions
- agent handoffs
- tool executions
- subagent calls
- peer-agent calls
- skill installs
- background service triggers

If something changes the system, operators should be able to answer:

- what happened?
- when did it happen?
- who triggered it?
- which agent ran it?
- which goal and task did it belong to?
- what output or side effect did it produce?

## The Three Pillars

### 1. Tracing

Tracing answers:

- what execution path did this run follow?

At the OS level, that means:

- envelope -> runner -> harness turn -> tools -> results

Useful identifiers:

- `trace_id`
- `run_id`
- `task_id`
- `goal_id`
- `session_id`
- `thread_key`
- `target_agent`

But tracing identifiers is not enough.

The OS should also trace execution usage.

That means at minimum:

- input tokens
- output tokens
- total tokens
- model/provider name
- price basis for that provider
- estimated cost in money

And for production-minded monitoring, the minimum usage/cost model should distinguish:

- input tokens
- output tokens
- total tokens
- pricing key
- estimated input cost
- estimated output cost
- estimated total cost

### 2. Monitoring

Monitoring answers:

- what is the current health and state of the system?

Examples:

- active runs
- blocked runs
- average turn latency
- queue depth
- token usage
- cost usage
- tool failure rate
- agent availability
- background job health

### 3. Operator Controls

Operator controls answer:

- what can a human do when the system is unhealthy or unsafe?

Examples:

- inspect a run
- inspect recent events
- cancel a run
- pause a team
- disable a channel
- disable a remote agent
- review install history

## User View vs Operator View

This distinction is important.

### User View

The user should mostly see:

- one conversation
- goal progress
- team progress
- deliverables

### Operator View

The operator should be able to see:

- active goals
- active tasks
- active runs
- agent ownership
- trace ids
- session ids
- logs
- failure state
- cancel / pause controls

Those are different surfaces.

Do not confuse them.

The clean operating model is:

- one work console for active conversation
- one operator console for system inspection and control

The next chapter will make that split explicit.

## The Minimum Trace Model

The first implementation should keep this small.

A traceable run should include:

- `trace_id`
- `run_id`
- `goal_id` optional
- `task_id` optional
- `session_id`
- `thread_key`
- `target_agent`
- `source`
- `status`
- `started_at`
- `finished_at`

And the first usage model should also include:

- `input_tokens`
- `output_tokens`
- `total_tokens`
- `estimated_input_cost`
- `estimated_output_cost`
- `estimated_total_cost`
- `pricing_key`

The important rule is:

token and money calculation belong in the execution core, not in the monitoring UI.

The runner or usage core should compute them.

Monitoring should only display and aggregate them.

That is enough to correlate most system behavior.

## The Minimum Operator Surfaces

The first operator-facing features should be:

- list active runs
- list recent finished runs
- inspect one run
- inspect recent events for one run
- cancel one active run

That already gives the OS a real operational backbone.

For the early local CLI path, the first concrete operator surfaces can start even smaller:

- `/routes`
- `/runs`
- `/session`
- `/sessions`

Those commands are enough to verify:

- which front-door thread is bound to which session
- which hosted agent handled recent turns
- which trace id and session id belonged to each run

The next meaningful operator metrics after that should be:

- tokens per run
- money per run
- aggregate token and money totals per team and per agent

## Current Local Monitoring Path

Today, the local monitoring path is simple and explicit:

- the runner persists run, route, session, and control state under `.mini-claw/`
- the operator console reads and aggregates that same state
- the operator dashboard refreshes on a timer

So current `make ops` monitoring is:

- file-backed
- same-machine
- shared-project-root

This is good enough for the first operational slice because it is:

- easy to inspect
- easy to test
- easy to learn

But it is still local mode.

## Distributed Monitoring Direction

For multi-machine Agent OS deployment, the operator path should evolve into:

- node / runner pushes state and events to a central control plane
- operator consoles connect to an operator API
- web / desktop / CLI operator surfaces all read the same backend

That is the point where monitoring stops being "read local files" and becomes a real control plane.

## Why This Must Be A First-Class Requirement

Without tracing and monitoring, multi-agent systems become black boxes.

You can see that something is wrong, but you cannot see:

- which team is blocked
- which agent is looping
- which session triggered the issue
- which remote skill install changed behavior

That is unacceptable for a real OS.

So observability is not a later nice-to-have.

It is part of the base design.

## Recommended Architecture

The first observability layer should likely include:

- `TraceRecord`
- `RunStatus`
- `RunRegistry`
- `OperatorEvent`
- `OperatorConsole` or later dashboard views

And the OS should propagate trace metadata through:

- envelopes
- runner
- session routing
- harness events
- background services

## Later Direction

Later, this can grow into:

- OpenTelemetry export
- distributed traces across ACP
- replay tools
- anomaly detection
- alerting

But the first local version should stay simple:

- explicit ids
- explicit run records
- explicit operator controls

That is enough to keep the system understandable while we build it.
