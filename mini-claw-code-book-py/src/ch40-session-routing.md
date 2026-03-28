# Chapter 40: Session Routing

By Chapter 39, the OS can model teams, goals, tasks, and runs.

It still does not know one critical thing:

which harness session should receive the next turn?

That is the job of session routing.

## The Core Problem

The outside world speaks in thread identities.

Examples:

- `cli:local`
- `telegram:123456`
- `dashboard:user-42`

The harness does **not** use those identifiers directly.

It uses `session_id`.

So the OS needs a mapping layer between:

- external conversation continuity
- internal harness session continuity

## The Mapping

The routing key should be:

```text
(target_agent, thread_key) -> session_id
```

This is better than:

- only `thread_key`

because the same external thread may talk to different hosted agents over time.

The OS should not lose that distinction.

## The First Concrete Shape

The first local router should use:

```text
.mini-claw/
  os/
    routes.json
```

Each route record should include:

- `target_agent`
- `thread_key`
- `session_id`
- `created_at`
- `updated_at`

That is enough to support local session continuity without introducing distributed coordination.

## A Narrow Scope

The first router should stay narrow.

It should route:

- external thread continuity
- to harness sessions

It should **not** store:

- goal state
- task state
- team membership
- run history

Those already have better homes.

This separation is important:

- routing decides where a turn goes
- coordination stores decide what the work means

## CLI First

The first real consumer should be the existing CLI path.

For the local CLI, the first thread key can simply be:

```text
target_agent = "superagent"
thread_key = "cli:local"
```

That gives the CLI a stable route without inventing user IDs or machine IDs yet.

The behavior should be:

1. on startup, resolve `("superagent", "cli:local")`
2. if the route exists and the session still exists, restore it
3. otherwise create a fresh session and bind the route

That makes Chapter 40 immediately real in `make cli`.

## Why This Is Better Than Creating A Fresh Session Every Time

Without routing, each new process launch creates a new session by default.

That is fine for an early tutorial.

But once the OS exists, the better default is:

- one front-door thread
- one resolved session
- explicit `/new` when the operator wants to branch

That makes the CLI feel more like a real front door instead of a stateless demo.

## What `/new`, `/resume`, and `/fork` Should Mean

Once routing exists, these commands should update the route too.

### `/new`

- create a fresh session
- bind the current route to the new session

### `/resume <id>`

- load the selected session
- rebind the current route to that session

### `/fork`

- create a forked session
- move the current route to the fork

That keeps the route aligned with the operator’s active session choice.

## Route Store vs Router

The first implementation should keep these separate:

### `RouteStore`

File-backed persistence for route records.

### `SessionRouter`

Routing logic:

- resolve
- bind
- resolve-or-create

That keeps the code easy to test.

## Required First-Slice Operations

The first router should support:

- `resolve(target_agent, thread_key)`
- `bind(target_agent, thread_key, session_id)`
- `resolve_or_create(target_agent, thread_key, cwd)`

And it should cooperate with the existing `SessionStore` from Chapter 29.

The router should not replace the session store.

It should sit above it.

## Missing Session Recovery

There is one important edge case:

What if the route exists, but the referenced session file is gone?

The first router should handle that cleanly:

- create a fresh session
- update the route to the new session

It should not leave the route in a broken state.

## Runtime Surface

The first CLI does not need a full route inspector yet.

But `/session` should at least be able to show:

- current session id
- current thread key
- current target agent

That is enough to make routing visible.

## What We Intentionally Skip

The first router does **not** need:

- cross-machine replication
- distributed leases
- conflict resolution across several writers
- route expiry policies
- channel-specific metadata stores

Those are later Agent OS concerns.

## Main Design Rule

Keep routing as a translation layer, not a giant state container.

The router should answer:

- where should this thread go?

It should not answer:

- what is the goal?
- what is the task?
- who owns the team?
- what happened in the run?

That is how the architecture stays clean.

## Implementation Target

The first concrete slice should introduce:

- `SessionRoute`
- `RouteStore`
- `SessionRouter`

And it should wire the CLI through:

- `("superagent", "cli:local")`

That gives the OS a real front-door routing layer before we build the turn runner in Chapter 41.
