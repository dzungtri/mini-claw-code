# Chapter 40: Session Routing

Once messages enter the bus and the OS knows which agents exist, it still needs to answer one critical question:

which session should receive this turn?

That is the job of session routing.

## The Core Problem

The user-facing identity is not the same as the internal harness session identity.

For example:

- external thread: `telegram:123456`
- target agent: `superagent`
- internal session: `sess_20260328_xxxxxx`

The OS needs to map between them.

## The Right Mapping

The router should think in:

```text
(target_agent, thread_key) -> session_id
```

That is better than:

- just `thread_key`

because several hosted agents may interact with the same external thread over time.

For the first implementation, the router should stay narrow:

- route external conversation continuity to harness sessions

It should **not** become the store for:

- goals
- tasks
- team membership
- planning state

Those belong in higher OS stores.

## Requirements

The first session router should:

- resolve existing sessions
- create a new session when none exists
- work with one or many hosted agents
- remain local and file-backed
- stay independent from team/task logic

It does **not** need:

- cross-machine replication
- distributed leases
- strong consistency protocols

## Architecture

The first version should include:

- `SessionRoute`
- `SessionRouter`
- `RouteStore`

The key contract is:

```python
session_id = router.resolve(
    target_agent="superagent",
    thread_key="cli:local",
)
```

That keeps session identity as an OS concern while preserving `HarnessAgent` as the runtime executor.
