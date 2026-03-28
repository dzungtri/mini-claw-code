# Chapter 44: Channels and Agent Teams

Once the OS can host many agents and many goals, the user still needs a coherent way to interact with it.

That means channels and teams need a clean user model.

## The Goal

We want:

- one front-door `superagent`
- one or many backend teams
- one or many user-facing channels

The user should usually talk to one front door, not directly to every internal agent.

## Channels

The first channels should be:

- CLI
- dashboard/web UI
- Telegram

Each channel should know:

- how to receive input
- how to send output
- how to identify the thread
- how to default or choose a target agent

## Teams

A team should include:

- `team_id`
- `lead_agent`
- `member_agents`
- `mission`
- `policy profile`

The user should see:

- current goal
- current team
- current progress
- deliverables

not raw internal agent chatter by default.

## Architecture

The first team-aware channel flow should be:

```text
user channel
  -> superagent
  -> team selection / team progress
  -> backend member task execution
  -> summarized response
```

That keeps the system understandable from the outside while still allowing rich backend coordination.
