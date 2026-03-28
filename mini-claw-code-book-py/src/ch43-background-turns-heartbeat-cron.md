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

## First Concrete Slice

The first implementation should stay deliberately local and small.

So the current slice should include:

- `HeartbeatService`
- `CronJob`
- `CronStore`
- `CronService`

And it should use the same local OS state root we already have:

```text
.mini-claw/
  os/
    cron_jobs.json
```

For heartbeat, the simplest useful rule is:

- read `HEARTBEAT.md`
- ignore empty lines, headers, and completed checkboxes
- if actionable content exists, publish one background envelope

That keeps the first version practical without building a full scheduler first.

## Current Local Flow

The first real local flow should now be:

```text
HeartbeatService.trigger()
  -> MessageEnvelope(kind="background_message")
  -> MessageBus inbound queue
  -> TurnRunner.run_from_bus()
  -> HarnessAgent
  -> RunRecord + session save + outbound message
```

And for cron:

```text
CronStore.due(now)
  -> CronService.fire_due()
  -> background envelopes
  -> MessageBus inbound queue
  -> TurnRunner.run_from_bus()
```

That gives us a real background-turn backbone without adding a daemon or remote scheduler yet.

## Team Targeting

If a service targets a team instead of one explicit agent, the service should resolve that to the team lead before publishing.

So the runner still receives one concrete target:

- `target_agent="superagent"`

not:

- `target_team="product-a"`

The team name is useful in service configuration, but the runner should still operate on one resolved hosted agent.

## What We Intentionally Skip

The first implementation should not try to do all of this yet:

- long-running cron daemon process
- OS startup service manager
- distributed heartbeat workers
- remote scheduled jobs
- ACP-triggered background scheduling
- retry queues and dead-letter queues

The goal of this chapter is smaller:

- prove that non-user work can enter the same OS path cleanly
- prove that the harness is still not bypassed
- prove that background turns are still observable and traceable
