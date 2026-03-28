# Chapter 36: From Harness to Agent OS

By Chapter 35, our project has a real harness runtime.

It can:

- manage tools
- load skills
- load MCP
- delegate to subagents
- compact context
- persist sessions
- apply control policies
- expose runtime events and surfaces

That is already much more than a simple agent loop.

But it is still not an Agent OS.

This chapter explains the next boundary clearly.

We will not implement the Agent OS yet.

We will design it first.

That matters, because once we introduce:

- multi-thread routing
- many hosted agents
- agent teams
- channel adapters
- gateways
- message buses
- background services
- ACP
- traceability and monitoring

the architecture changes again.

If we do that carelessly, the runtime becomes messy very quickly.

So the goal of this chapter is:

- define the difference between a harness and an Agent OS
- identify which responsibilities stay in the harness
- identify which responsibilities move outside it
- define the difference between subagents and hosted peer agents
- define the front-door `superagent` role
- define teams, goals, tasks, and runs
- place ACP at the right architectural boundary
- make observability a first-class requirement
- design the next folder and module shape

## Core Vocabulary

Before we continue, we need one stable vocabulary.

If these terms drift from chapter to chapter, the whole Agent OS design becomes confusing.

So from here onward, this book will use the following meanings.

### `HarnessAgent`

One turn runtime.

It is responsible for:

- prompt assembly
- tool execution
- memory
- context handling
- subagents
- control plane
- session restore/save

It is **not** the whole Agent OS.

### `Hosted Agent`

A named agent runtime managed by the OS.

Examples:

- `superagent`
- `pipi`
- `reviewer`

A hosted agent is usually built from a harness definition plus OS-level routing.

### `Subagent`

A temporary delegated child run inside one harness turn.

A subagent is:

- short-lived
- bounded
- owned by one parent harness run

A subagent is **not** a peer hosted agent.

### `Thread Key`

The external routing identity.

Examples:

- `cli:local`
- `telegram:123456`
- `ws:client-42`

The OS uses this to identify the external conversation thread.

### `Session ID`

The internal persisted harness conversation identity.

This is the thing Chapter 29 stores and restores.

So:

- `thread_key` is external
- `session_id` is internal

The OS maps:

```text
(target_agent, thread_key) -> session_id
```

### `Envelope`

A normalized OS message object.

It is the thing that moves through the message bus.

An envelope should carry enough information to route one turn safely.

### `Message Bus`

The transport-neutral internal pipeline that carries envelopes and events between OS components.

The bus does not reason.

It only moves work.

### `Agent Registry`

The OS store that knows which hosted agents exist and how to build them.

It answers:

- what agents exist?
- how are they configured?

### `Team Registry`

The OS store that knows how hosted agents are organized into working groups.

It answers:

- which agents belong to which team?
- who is the lead?
- what is the team mission?

### `Goal`

A top-level user or system objective.

Examples:

- build feature A
- launch campaign B
- investigate outage C

### `Task`

A unit of work assigned to one agent.

Examples:

- implement endpoint
- review PR
- draft landing page copy

### `Run`

One execution attempt of a task or turn.

A run is the thing we should later trace and monitor.

### `Channel`

A user-facing or system-facing communication adapter.

Examples:

- CLI
- dashboard
- Telegram
- WebSocket

A channel knows how to receive and send messages.

It does not own the harness runtime.

### `Gateway`

A protocol-facing boundary for external systems.

Examples:

- ACP
- future HTTP/WebSocket control APIs

Gateways are richer than simple channels because they often manage sessions, protocol capabilities, and structured updates.

### `Node`

One execution host for one or more hosted agents.

A node may be:

- the same machine as the operator console
- another process on the same machine
- a remote machine reached over the network

This term matters once the OS stops being single-machine only.

### `Control Plane`

The part of the OS that tracks and coordinates:

- routes
- runs
- sessions
- operator actions
- monitoring state

In local mode, this can be file-backed.

In distributed mode, it should evolve into a real shared service.

### `Background Service`

A non-user producer of work.

Examples:

- cron
- heartbeat
- alert ingestion

Background services should create envelopes and publish them into the OS.

They should not bypass the runner.

### `Operator View`

The internal control and monitoring surface for humans who operate the OS.

This is different from the normal user view.

An operator view should expose:

- runs
- traces
- logs
- task state
- cancellation controls

### `User View`

The normal end-user surface.

The user should mostly see:

- one conversation
- progress summaries
- deliverables

Not raw internal system state by default.

## The Core Distinction

Our current `HarnessAgent` is a **turn runtime**.

It is responsible for one active conversation loop:

1. receive a user turn
2. build active context
3. ask the model
4. execute tools
5. delegate to subagents if needed
6. update state
7. emit runtime events
8. finish the turn

That is exactly what a harness should do.

An Agent OS is the next ring around that runtime.

It is responsible for:

- getting turns into the harness
- getting results back out
- managing many channels and many sessions
- managing many hosted agents
- creating turns from background services
- routing messages to the correct runtime

So:

- harness = turn runtime
- Agent OS = environment that hosts and routes many harness turns

## The Best Combined Lesson From The Reference Projects

Each reference project gives us a different lesson.

### DeepAgents

DeepAgents is strongest at:

- building a rich child runtime stack
- treating subagents as real runtime constructs
- exposing ACP as a protocol-facing adapter

Its ACP package is especially important because it shows:

- session creation
- session config options
- model switching
- protocol-driven streaming updates

### DeerFlow

DeerFlow is strongest at:

- lead-agent orchestration
- clarification-first policy
- runtime middleware and policy layering
- treating the lead agent as a task orchestrator, not just a tool caller

### Mimiclaw

Mimiclaw is strongest at:

- the Agent OS boundary
- message bus separation
- channel adapters
- heartbeat and cron as background turn producers
- treating the agent loop as one subsystem inside a larger host

That combination gives us the right target:

> build a strong harness first
> then host many harnesses inside an Agent OS

## What Stays Inside The Harness

These responsibilities should remain inside `HarnessAgent`:

- turn execution
- prompt assembly
- tool execution
- MCP integration
- skill loading
- subagent orchestration
- context durability
- memory updates
- control-plane checks
- runtime events
- artifact tracking
- session snapshot save/restore

These are all part of a **single turn runtime**.

They describe how the agent behaves once a turn has already reached it.

## What Moves Outside The Harness

These should belong to the future Agent OS layer:

- inbound channel adapters
- outbound channel delivery
- gateway APIs
- message routing
- mapping external thread identities to internal sessions
- background turn producers
- schedulers and cron
- heartbeat triggers
- many hosted agents
- agent-to-agent routing
- tracing
- monitoring
- operator controls

These are not really “agent thinking” concerns.

They are host-environment concerns.

That is why they should not keep growing inside `harness.py`.

## Single Agent, Subagents, and Multi-Agent Systems

This distinction is critical.

### Single Agent

This is one `HarnessAgent`.

It has:

- one runtime
- one active turn loop
- one session space

### Subagents

These are temporary delegated workers created by one harness during one parent task.

They are:

- short-lived
- scoped to one parent objective
- not first-class long-lived identities

They belong inside the harness runtime.

### Hosted Peer Agents

These are different.

Examples:

- `superagent`
- `pipi`
- `reviewer`
- `ops-agent`
- `research-agent`

Each one may have:

- its own harness config
- its own memory
- its own skills
- its own MCP config
- its own session namespace
- its own subagents

These belong to the Agent OS layer.

So the real design rule is:

> subagents are delegated child runs inside one harness
> peer agents are hosted runtimes managed by the Agent OS

That boundary keeps the system understandable.

## The Front Door Agent

In a real Agent OS, the user should usually not talk directly to many backend agents.

The user should mostly talk to one front door.

We will call that front door:

- `superagent`

This matches the role you described well:

- the user-facing window
- the main accountable coordinator
- the agent that understands the user goal
- the agent that reports progress back clearly

So the user model becomes:

```text
user
  ↕
superagent
  ↕
agent teams
  ↕
team members
```

This is much better than:

- user ↔ many internal agents directly

because it keeps the system coherent from the user perspective.

## The Team Model

Once we have more than one hosted peer agent, we should group them into teams.

Examples:

- `product-a`
- `product-b`
- `marketing`
- `research`
- `operations`

Each team should have:

- `team_id`
- `name`
- `mission`
- `lead_agent`
- `member_agents`
- `workspace`
- `task_board`
- `memory`
- `policy profile`

For example:

```text
team: product-a
  lead: eng-manager
  members:
    - backend-dev
    - frontend-dev
    - tester
    - designer
```

Another:

```text
team: marketing
  lead: marketing-manager
  members:
    - copywriter
    - seo-agent
    - social-agent
```

This is one of the most important shifts from a harness to an OS:

the OS does not just host agents.

It hosts **organized working groups** of agents.

## The Goal / Task / Run Hierarchy

To keep the OS understandable, we need explicit state objects.

The cleanest hierarchy is:

```text
user thread
  -> goal
     -> team
        -> tasks
           -> runs
```

### User Thread

The external conversation.

Examples:

- dashboard chat
- CLI session
- Telegram chat

### Goal

The top-level outcome the user wants.

Examples:

- build feature A
- prepare a marketing campaign
- investigate a production incident

### Team

The execution group responsible for that goal.

### Task

A unit of work assigned to one agent.

Examples:

- implement API endpoint
- review PR
- draft landing page copy
- run regression tests

### Run

One concrete execution attempt of a task.

This hierarchy gives the OS a real management model.

It is much stronger than “just send messages to agents”.

## The Roles Inside A Team

Once teams exist, not every agent should behave the same way.

### `superagent`

Owns:

- user communication
- top-level goal understanding
- team selection
- high-level progress reporting
- escalation and reprioritization

### Team Lead

Owns:

- one team goal
- member task assignment
- task board management
- synthesis of team outputs

### Team Member

Owns:

- execution of assigned tasks
- use of skills, MCP, workspace, and subagents
- progress updates and deliverables

This gives the OS a structure that feels much closer to a real software or operations team.

## A Better Mental Model

Use this model from now on:

```text
channel / gateway / background service
                ↓
             Agent OS
                ↓
 agent registry + team registry + session router + bus
                ↓
      one selected hosted HarnessAgent
                ↓
 tools / subagents / workspace / MCP / memory
                ↓
      traces / logs / metrics / controls
```

That is much closer to real systems than:

```text
CLI → big agent file → everything
```

## The Four Rings

At this point, the project can be understood as four rings.

### Ring 1: Agent Core

This is where the tutorial started.

It includes:

- core message types
- tool definitions
- providers
- simple loop

### Ring 2: Agent Harness

This is where we are now.

It includes:

- bundled tools
- memory
- context compaction
- workspace
- subagents
- MCP
- control plane
- sessions
- runtime events
- surfaces

This is the runtime product.

### Ring 3: Agent OS

This is the host environment around the harness.

It includes:

- bus
- agent registry
- team registry
- session router
- channels
- gateways
- schedulers
- heartbeat
- tracing and monitoring
- operator controls

### Ring 4: Agent Network

This is the future outer ring.

It includes:

- ACP-based external agent interaction
- remote hosted agents
- team topologies
- cross-process or cross-machine agent communication

We do not need Ring 4 immediately.

But we should not design Ring 3 in a way that blocks it.

## Why The Bus Matters

Once multiple producers can create turns, we need a message bus.

Examples:

- a CLI prompt creates a new user turn
- a WebSocket client creates a new user turn
- a cron job creates a scheduled turn
- a heartbeat creates a maintenance turn
- one hosted agent may request work from another

All of those should arrive at the same system in a common format.

That means we need a normalized message envelope.

For example:

```json
{
  "source": "telegram",
  "target_agent": "superagent",
  "thread_key": "telegram:123456",
  "kind": "user_message",
  "content": "Ask Pipi to review the deployment plan",
  "metadata": {
    "chat_id": "123456"
  }
}
```

The bus does not do reasoning.

It only:

- carries normalized messages
- decouples producers from consumers
- lets the OS route work cleanly

The bus is especially important once we support many teams and many agents at once.

It lets the system stay smooth even when:

- one user has several active goals
- several teams are running in parallel
- background services inject new work
- one agent asks another agent to take a task

## Why The Agent Registry Matters

As soon as we support more than one named agent, the OS needs a registry.

For example:

```text
agent_registry
  superagent -> harness profile A
  pipi       -> harness profile B
  reviewer   -> harness profile C
```

Each entry should define:

- agent name
- harness config/profile
- memory roots
- prompt template
- MCP defaults
- default subagent config
- allowed channels or visibility rules

This is one of the most important architectural steps.

Without an agent registry, a “multi-agent system” becomes just a pile of special-case code.

## Why A Team Registry Matters

As soon as agents start working in groups, the OS also needs a team registry.

For example:

```text
team_registry
  product-a  -> lead=eng-manager, members=[backend-dev, frontend-dev, tester]
  marketing  -> lead=marketing-manager, members=[copywriter, seo-agent]
```

This is not the same as the agent registry.

The agent registry answers:

- what agents exist?

The team registry answers:

- how are those agents organized for a specific mission?

That difference matters a lot.

## Why Channels Matter

A channel adapter is responsible for transport-specific work.

Examples:

- terminal input
- WebSocket JSON frames
- Telegram updates
- future web UI requests

A channel should know:

- how to receive input
- how to send output
- how to identify a thread
- how to select or default a target agent

A channel should **not** know:

- how to run the harness loop
- how to build prompts
- how to execute tools

That belongs to the harness.

## Why Background Turns Matter

One important shift happens at the Agent OS level:

not every turn comes from a human typing into the current terminal.

For example:

- cron can inject a scheduled reminder or task
- heartbeat can inject a maintenance turn
- a webhook can inject an external event

These should be treated as first-class turn sources.

That means the system needs:

- a common message envelope
- a bus
- a runner that can turn a bus message into one harness turn

This is exactly where Mimiclaw is useful as a reference.

Its heartbeat and cron services do not modify the agent loop.

They simply generate new work for it.

That is the correct architectural pattern.

The same rule should apply to teams:

- cron should target a team or agent
- heartbeat should target a team or agent
- monitoring alerts should target the correct owner

Background services should not “do the work”.

They should create work for the OS to route.

## Session Identity At The OS Layer

In Chapter 29, we said:

- `session_id` is the persisted identity for now
- `thread_id` is reserved for later

This is the later.

At the Agent OS layer, we should distinguish:

- `session_id`
- `thread_key`

### `session_id`

The internal persisted harness session.

This maps to:

- snapshot files
- todos
- audit log
- token usage
- working conversation state

### `thread_key`

The external routing identity.

Examples:

- `cli:local`
- `ws:client-42`
- `telegram:123456`
- `cron:daily-report`

In a multi-agent OS, the router should really think in:

```text
(target_agent, thread_key) -> session_id
```

That gives us a clean split:

- channels think in `thread_key`
- the OS resolves the target agent
- the harness persists `session_id`

And once teams exist, the router may also need to keep:

```text
goal_id -> team_id
team_id + target_agent + thread_key -> session_id
```

Not every implementation needs that immediately.

But the design should leave room for it.

## ACP Changes The Picture

ACP matters because it is more than a transport.

From the DeepAgents ACP examples, the important lessons are:

- ACP creates real sessions
- ACP can expose per-session configuration
- ACP supports structured streaming updates
- ACP allows mode and model switching without losing session identity

That means ACP belongs at the Agent OS boundary.

Not inside `HarnessAgent`.

Why?

Because ACP is about:

- client capabilities
- session creation
- session configuration
- structured updates
- protocol negotiation

Those are host-facing concerns.

The harness should stay the execution engine behind that protocol.

## ACP In Our Design

For this project, ACP should be treated as one kind of gateway adapter.

So:

- CLI is one channel
- Telegram is one channel
- WebSocket is one channel
- ACP is one gateway/protocol adapter

But ACP is stronger than a simple text channel because it can expose:

- session config options
- richer client capabilities
- structured content blocks
- editor-facing workflows

So the Agent OS should eventually provide an ACP server that can:

1. create or resume a session
2. select the target hosted agent
3. stream harness events back to the client
4. allow session-level config changes

That means ACP is not replacing the harness.

It is wrapping it.

ACP also becomes interesting for agent-to-agent communication across machines.

That does not mean every internal call should use ACP.

A better split is:

### Local Same-Machine Communication

Use:

- local bus
- local runner calls

### Cross-Process Or Cross-Machine Communication

Use:

- ACP

That lets the OS support:

- one computer
- many computers
- local teams
- remote worker agents

without forcing one heavy protocol on every internal call.

## Single Computer And Multi Computer Deployment

We should design for both from the start.

### Single Computer

Everything is local:

- UI
- Agent OS
- all teams
- all harness agents
- local bus

This should be the first implementation path.

### Multi Computer

Some agents or teams may be remote:

- a central Agent OS still owns goals and routing
- remote workers communicate via ACP or another gateway
- task envelopes may cross the network

So the OS should be able to think in:

```text
agent_registry
  superagent -> local
  pipi -> local
  reviewer -> remote(acp://machine-b/reviewer)
  marketer -> remote(acp://machine-c/marketing)
```

This is why ACP belongs at the OS boundary, not inside one harness runtime.

## Agent Teams

Once we have hosted peer agents, we can introduce teams.

For example:

```text
team: content-studio
  lead: superagent
  members:
    - pipi
    - reviewer
    - publisher
```

This is not the same as subagents.

A team member is a named hosted agent with its own configuration and identity.

That means:

- a lead agent may delegate to a peer agent
- a peer agent may still use its own subagents internally

So later we may have both:

- OS-level peer delegation
- harness-level child delegation

That is why the boundaries above matter so much.

## The Minimal Agent OS Services

The first version should stay very small.

We do not need everything at once.

The smallest useful Agent OS layer is:

1. `bus`
2. `agent_registry`
3. `team_registry`
4. `session_router`
5. `runner`
6. `channels`

That is enough to support:

- multiple turn producers
- stable session routing
- one or many hosted agents
- one or many teams
- one harness runtime per turn

Later we can add:

- `cron`
- `heartbeat`
- `gateway`
- `acp`
- `teams`

## Proposed Folder Direction

We should still keep the codebase readable.

So we should not explode into too many folders too early.

A good next shape is:

```text
mini_claw_code_py/
  agent.py
  planning.py
  harness.py
  session.py
  config.py
  mcp.py
  memory.py
  subagent.py
  ...

  tui/
    app.py
    console.py
    __main__.py

  os/
    envelopes.py
    bus.py
    agent_registry.py
    team_registry.py
    goal_store.py
    task_store.py
    session_router.py
    runner.py
    channels/
      cli.py
      websocket.py
      telegram.py
    gateway/
      acp.py
    services/
      cron.py
      heartbeat.py
    teams.py
```

This gives us a clean boundary:

- flat harness modules stay readable
- Agent OS modules live in one separate package

That is much better than moving everything into nested folders immediately.

## The Next Runtime Contracts

Once the OS layer exists, the harness should expose one simple entrypoint:

```python
result = await harness.run_turn(
    session_id=session_id,
    message=Message.user("..."),
    event_queue=queue,
)
```

And the OS should expose a routing contract like:

```python
session_id = session_router.resolve(
    target_agent="pipi",
    thread_key="telegram:123456",
)
```

And at the team level, the OS will eventually need contracts like:

```python
goal_id = goal_store.create(
    owner_thread="telegram:123456",
    requested_by="superagent",
    objective="Build feature A",
)
```

and:

```python
task_store.assign(
    goal_id=goal_id,
    team_id="product-a",
    agent_name="frontend-dev",
    title="Build settings page",
)
```

That is important.

The OS should not need to know:

- how prompt assembly works
- how memory updates work
- how MCP works

It should only know how to:

- pick the hosted agent
- route a turn
- invoke a turn
- stream the resulting events

## What We Should Not Build Yet

Even if the references show them, we should not jump to all of these immediately:

- Telegram bot integration
- Feishu integration
- full WebSocket gateway
- cron persistence
- heartbeat files
- multi-user auth
- remote ACP meshes
- distributed agent coordination

Those are useful later.

But the first teaching step should be much smaller:

- build the Agent OS boundary
- build a message envelope
- build an agent registry
- build a team registry
- build a session router
- make the CLI use the OS path

That is enough to prove the architecture.

## Recommended Chapter Sequence After This

I would continue like this:

1. `Chapter 37: Message Envelopes and the Bus`
2. `Chapter 38: Agent Registry and Hosted Agents`
3. `Chapter 39: Teams, Goals, Tasks, and Runs`
4. `Chapter 40: Session Routing`
5. `Chapter 41: Running Harness Turns From the Bus`
6. `Chapter 42: ACP Gateway and Session Modes`
7. `Chapter 43: Background Turns with Heartbeat and Cron`
8. `Chapter 44: Channels and Agent Teams`
9. `Chapter 46: Traceability, Monitoring, and Operator Controls`

That order is clean because it moves from:

- internal OS plumbing

to:

- external protocols and system services

## The Main Insight

The most important architectural shift is this:

> A harness runs turns.
> An Agent OS routes work to hosted harness turns.

That means we should stop trying to make `HarnessAgent` own:

- channel protocols
- message dispatch
- background schedulers
- gateway services
- peer agent hosting
- agent-to-agent routing

Those belong to the next outer ring.

And that is exactly why designing the boundary now matters.

We are no longer building only an agent runtime.

We are preparing to host many runtimes inside a larger system.
