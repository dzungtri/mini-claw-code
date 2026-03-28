# Chapter 44: Channels and Agent Teams

Once the OS can host many agents and many goals, the user still needs a coherent way to interact with it.

That means channels and teams need a clean user model.

## The Goal

We want:

- one front-door `superagent`
- one or many backend teams
- one or many user-facing channels

The user should usually talk to one front door, not directly to every internal agent.

That means the default user-facing rule should be:

- channels route normal user turns to `superagent`

Direct routing to peer agents should be treated as:

- an advanced admin feature
- or an internal system capability

## Channels

The first channels should be:

- CLI
- dashboard/web UI
- Telegram

Each channel should know:

- how to receive input
- how to send output
- how to identify the thread
- how to default a target agent

For the first version, that default target agent should usually be `superagent`.

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

Operators, however, should later be able to inspect the raw execution state when needed.

## Workspace Boundaries

Workspace design becomes more important once we have many hosted agents and many teams.

The safest default is:

- one team gets one primary workspace
- agents inside that team may share that workspace if the mission requires collaboration
- each agent should also have its own scratch area
- different teams should default to different workspaces

So a software delivery team might intentionally share one repository workspace:

- `team workspace = product-a repo`
- `agent scratch = product-a/.agent-work/<agent-name>/...`

But a marketing team should usually not share that same root by default.

It should have its own workspace and artifact/output area.

The main design rule is:

- collaboration happens through shared team workspaces and explicit artifacts
- not through every team mutating the same root blindly

## Cross-Team Collaboration

When teams need to collaborate, the cleaner primitive is:

- artifact handoff
- summarized outputs
- explicit shared resources

not:

- every team writing directly into every other team workspace

That keeps ownership and security much clearer.

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

So the UI model should likely split into:

- user view
- operator view
