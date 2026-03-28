# Chapter 43: Background Turns with Heartbeat and Cron

Not every turn should come from a human typing into the UI.

Some turns should come from the system itself.

That is where heartbeat and cron belong.

## The Goal

We want background services that can create new work without modifying the harness runtime.

Examples:

- daily summary
- reminder to check a project
- maintenance review
- follow-up on pending goals

## Requirements

Background services should:

- create normalized envelopes
- target a specific agent or team
- publish into the same OS bus
- remain decoupled from the harness
- emit observable service events

If a service targets a team, the OS should resolve that to:

- the team lead
- or another explicit front-door agent for that team

The runner should still receive one concrete target agent.

They should **not**:

- call tools directly
- bypass the runner
- mutate harness state by themselves

## Architecture

The first services should be:

- `HeartbeatService`
- `CronService`

Both should follow the same rule:

```text
service -> envelope -> bus -> runner -> harness turn
```

That is the clean architecture.

And each service-triggered turn should still be traceable as one normal run inside the OS.
