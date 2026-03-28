# Chapter 47: Operator Console and Control API

By Chapter 46, we have already decided that an Agent OS must be traceable and monitorable.

That still leaves one practical problem:

how does an operator actually use that information while the system is busy working?

If `make cli` is acting as the front-door work console, then while it is streaming one active turn, that same terminal is a poor place to monitor and control the rest of the system.

So the Agent OS should explicitly split two roles:

- the work console
- the operator console

This chapter defines that split as a real backend architecture, not just as a UI idea.

## The Production Goal

We want one backend that can support:

- one or many work consoles
- one or many operator consoles
- later web dashboards
- later desktop admin apps
- later HTTP, WebSocket, gRPC, or ACP-based admin surfaces

That means the key design is **not** the terminal UI.

The key design is the operator backend boundary.

## Two Different Jobs

The easiest way to keep the architecture clean is to recognize that the two consoles serve different jobs.

### 1. Work Console

This is the user-facing console.

It should optimize for:

- one active conversation
- one active session
- fast prompt/response flow
- immediate artifacts and short progress updates

In our project today, that is `make cli`.

### 2. Operator Console

This is the administrative console.

It should optimize for:

- many runs
- many sessions
- many routes
- many teams
- background services
- health views
- control actions

Later, that may become:

- `make ops`
- a web admin dashboard
- a desktop admin app

The important point is:

the operator console is not “another chat UI”.

It is a systems view.

## Why This Split Must Be Explicit

Without this split, the front-door CLI becomes overloaded.

It tries to be:

- the user chat surface
- the run monitor
- the route inspector
- the task manager
- the admin control panel

That is the wrong direction.

The better design is:

- work console for work
- operator console for the system

That sounds simple, but it has a major consequence:

the two consoles should not each implement their own private logic.

They should share one backend.

## One Backend, Many Presentations

The operator console should **not** be implemented as a second pile of direct file reads and ad hoc state inspection.

Instead, the OS should expose one operator backend surface.

Then several presentations can sit on top:

- terminal monitor
- web dashboard
- desktop app
- later gRPC / websocket / HTTP clients

That means the architecture should look like:

```text
stores + runner + bus + registries
               |
        operator service
         /      |      \
     ops cli   web ui   desktop ui
```

This is one of the most important design choices in the Agent OS.

If we get this wrong, every monitoring surface will reimplement:

- the same reads
- the same correlations
- the same control rules

That produces drift very quickly.

## The Backend Boundary

The operator backend should sit **above** stores and runner state, not inside presentation code.

That means:

- TUI/CLI command handlers should not read files directly
- the operator backend should query stores and live runtime state
- presentation layers should only render returned data and submit commands

This is the same design rule we already used for:

- harness config
- session routing
- turn running

The UI should not own the system logic.

## Operator UX Goals

Before we implement `make ops`, we should define what a good operator terminal must feel like.

The target is closer to:

- `htop`
- `lazygit`
- `k9s`
- a task manager

than to a normal chat UI.

The operator needs to answer questions like:

- what is running right now?
- which team is busy?
- which hosted agent owns the work?
- are subagents active under a parent run?
- how many turns has this run used?
- how many estimated tokens has it consumed?
- how much money has this run already consumed?
- how full is the current context window?
- is anything blocked, looping, or failing?

So the operator UX should optimize for:

- dense situational awareness
- fast drill-down
- clear status colors and counters
- keyboard-first control
- one-line command entry for control actions

And usage should always be shown together with money:

- prompt tokens
- completion tokens
- total tokens
- estimated per-run cost
- aggregate cost per team and per agent

## UI Technology Choice

For this project, the best terminal technology choice for the operator console is:

- `Textual` for the operator/admin TUI
- `Rich` remains fine for the simpler work console

Why `Textual` is the right fit:

- panel-based layouts
- keyboard focus and key bindings
- screen-to-screen navigation
- inspect/detail views
- input widgets
- timers and live refresh
- better long-term fit for a production-style terminal app

Why not keep building the operator console with only `Rich`:

- Rich is excellent for rendering
- but a complex operator surface quickly turns into ad hoc focus, layout, and navigation management

Why not choose a lower-level alternative first:

- `prompt_toolkit` is strong for REPLs and command-oriented UIs
- `urwid` is capable, but it is not the best fit for the tutorial ergonomics and long-term app structure we want here

So the clean design is:

- keep the current Rich-based work console for now
- build `make ops` with Textual

That gives the more complex operator/admin surface the right tool without forcing the simpler user work console to migrate immediately.

Textual is also a better fit for the interaction model we want:

- selectable tables
- row highlight and click interaction
- detail panes
- keyboard-driven copy and inspect actions
- a persistent command bar at the bottom of the screen

## Core UX Principle

The operator console should always have two layers:

1. a realtime dashboard
2. a command line / control line

The dashboard answers:

- what is happening now?

The command line answers:

- what do I want to do about it?

That combination is much stronger than either:

- a static report
- or a pure REPL

## Current `make ops` Interaction Model

The current operator console should follow these rules:

- default focus lands on the active runs table
- arrow keys move the selected row
- the detail pane updates from the selected run, route, or session
- `Tab` and `Shift+Tab` move focus between panels and the command bar
- `Ctrl+Y` copies the focused run or session id
- `/` focuses the command bar
- `/quit` and `Ctrl+Q` both exit

That makes the operator UI feel closer to:

- `tig`
- `htop`
- `k9s`

than to a normal chat client.

## The Main Screen

The first screen should be a live system dashboard.

It should show one-screen answers to:

- active runs
- active teams
- active hosted agents
- route/session pressure
- token/context pressure
- recent warnings

The operator should not need to page through several screens just to know whether the system is healthy.

## Proposed Layout

The terminal layout should be divided into five zones:

```text
+----------------------------------------------------------------------------------+
| AgentOS Ops                                                      profile=local   |
| time=2026-03-29T10:15:00Z  active_runs=4  queued=2  warnings=1  bus_events=128  |
+-----------------------------------+----------------------------------------------+
| Teams                              | Active Runs                                  |
|-----------------------------------|----------------------------------------------|
| product-a       3 runs  healthy    | > run_91ab  superagent   in_progress         |
| marketing       1 run   healthy    |   goal=goal_21  task=-  trace=trace_aa       |
| research        0 run   idle       |   turns=7  est_tokens=12.3k  est_cost=$0.08  |
| default         0 run   idle       |   ctx=61%                                     |
|                                   |   run_91ac  backend-dev  in_progress          |
|                                   |   goal=goal_21  task=task_88  trace=trace_ab |
|                                   |   turns=4  est_tokens=6.8k  est_cost=$0.03   |
|                                   |   ctx=42%                                     |
+-----------------------------------+----------------------------------------------+
| Agents                             | Sessions / Routes                            |
|-----------------------------------|----------------------------------------------|
| superagent      busy  1 run        | cli:local        -> sess_abc123              |
| backend-dev     busy  1 run        | telegram:9981    -> sess_abc900              |
| frontend-dev    idle  0 run        | ws:client-42     -> sess_abd110              |
| tester          idle  0 run        |                                              |
+-----------------------------------+----------------------------------------------+
| Events / Alerts                                                                   |
|----------------------------------------------------------------------------------|
| 10:14:58  WARN  run_91ab nearing context limit (ctx=61%)                         |
| 10:14:53  INFO  subagent started under run_91ab                                   |
| 10:14:49  INFO  route rebound cli:local -> sess_abc123                            |
+----------------------------------------------------------------------------------+
| :help  /inspect run run_91ab  /cancel run run_91ab                                |
+----------------------------------------------------------------------------------+
```

That should be the default mental model:

- top bar = system summary
- center panels = live state
- lower panel = recent events
- bottom line = operator command entry

## Why This Layout Works

It gives the operator:

- a stable summary line
- a left-to-right “organization then execution” flow
- one event feed for recent changes
- one consistent place to type control commands

This is much better than a terminal that prints infinite logs downward.

The operator needs structure, not noise.

## Current Local Data Path

Today, `make ops` is still local-first.

It is not reading from a network daemon.

It is reading the same local OS state that the runner writes:

```text
make cli -> TurnRunner -> .mini-claw/os + .mini-claw/sessions
make ops -> OperatorService -> same .mini-claw state
```

So current realtime monitoring is based on:

- one shared project root
- one shared local filesystem
- periodic refresh in the operator TUI

This is why several terminals on the same machine can already cooperate.

It is also why a remote `make ops` on another machine is not the same thing yet.

## The Distributed Evolution

For multi-machine deployment, the cleaner progression is:

1. local mode
   - shared filesystem state
   - timer-based refresh
2. node mode
   - durable store plus append-only event log
3. distributed mode
   - central control plane service
   - operator API
   - authenticated node registration
   - event streaming to operator clients

At that point:

- `make ops` becomes one operator presentation
- web and desktop apps can reuse the same backend
- remote runners can publish into the same control plane

## Primary Panels

The first implementation should likely start with these panels.

### 1. Top Status Bar

This should show:

- current mode / profile
- current time
- active run count
- queued work count later
- warning count
- maybe bus event rate later

This is the “is the system calm or noisy?” bar.

### 2. Teams Panel

This should show:

- team name
- team health
- active run count
- maybe blocked task count later

The operator should be able to tell quickly:

- which team is currently hot
- which team is idle

### 3. Active Runs Panel

This is the most important panel.

Each visible run row should show:

- `run_id`
- `agent_name`
- `status`
- `goal_id`
- `task_id` if present
- `trace_id`
- turn count
- token count
- money
- context pressure percent

This is where the operator spends most of the time.

### 4. Agents Panel

This should show:

- hosted agent name
- current state:
  - busy
  - idle
  - paused later
  - disabled later
- active run count

This panel answers:

- which agents are actually doing work now?

### 5. Sessions / Routes Panel

This should show:

- `thread_key`
- `target_agent`
- `session_id`

This answers:

- where is external traffic routed right now?

### 6. Events / Alerts Panel

This should show the latest operator-significant events:

- run started
- run finished
- subagent started
- warning raised
- route rebound
- cancellation requested
- failure detected

This is not a raw log tail.

It is a filtered operator event feed.

## Realtime Metrics Per Run

For each active run, the operator console should eventually expose:

- current status
- started time
- elapsed time
- hosted agent
- parent team
- goal/task if present
- turn count
- tool call count
- subagent count
- estimated input tokens
- estimated output tokens
- total token usage
- estimated input cost
- estimated output cost
- estimated total cost
- pricing key or pricing profile
- current context pressure percent
- warning flags

This is how the operator understands if a run is:

- healthy
- expensive
- near context exhaustion
- looping
- under heavy delegation

Money matters here because AgentOS is not only a process system.

It is also a cost system.

An operator should be able to see:

- this run is healthy but expensive
- this agent is consuming tokens too quickly
- this team is cheap but slow

## Realtime Metrics Per Agent

For each hosted agent, the operator console should eventually expose:

- current state
- current run count
- recent run success/failure counts
- token usage totals
- money totals
- average turn latency later
- last active time

That helps answer:

- is this agent overloaded?
- is it idle?
- is it failing more than others?

## Realtime Metrics Per Team

For each team, the operator console should eventually expose:

- active goals
- active tasks
- active runs
- blocked tasks
- failed runs
- aggregate token usage
- aggregate money usage

This helps the operator see the system organizationally, not just process-by-process.

## Selection Model

The operator terminal should be selection-based.

That means:

- arrow keys move focus
- one panel is “active”
- Enter drills into the selected item
- Esc or `q` returns

This is a much better model than requiring slash commands for every navigation step.

The command line should remain available, but selection should be the default navigation path.

## Inspect View

When the operator selects a run, the console should open an inspect screen.

Example:

```text
+----------------------------------------------------------------------------------+
| Inspect Run: run_91ab                                                            |
| status=in_progress  agent=superagent  session=sess_abc123  trace=trace_aa       |
| goal=goal_21  task=-  started=10:14:40Z  elapsed=00:00:20                        |
+-----------------------------------+----------------------------------------------+
| Summary                            | Runtime Metrics                              |
|-----------------------------------|----------------------------------------------|
| turns=7                            | est_input_tokens=10.8k                       |
| tool_calls=12                      | est_output_tokens=1.5k                       |
| subagents=2                        | total_tokens=12.3k                           |
| current_mode=execution             | est_input_cost=$0.05                         |
|                                   | est_output_cost=$0.03                        |
|                                   | est_total_cost=$0.08                         |
|                                   | context_pressure=61%                         |
+-----------------------------------+----------------------------------------------+
| Recent Operator Events                                                            |
|----------------------------------------------------------------------------------|
| 10:14:58 WARN  nearing context limit                                             |
| 10:14:53 INFO  subagent started: packaging-helper                                |
| 10:14:49 INFO  route resolved cli:local -> sess_abc123                           |
+----------------------------------------------------------------------------------+
| Recent Harness Events                                                             |
|----------------------------------------------------------------------------------|
| tool_call: write_todos                                                           |
| subagent_started: packaging-helper                                               |
| memory_update: queued                                                            |
+----------------------------------------------------------------------------------+
| :back  /cancel run run_91ab  /tail trace trace_aa                                |
+----------------------------------------------------------------------------------+
```

That inspect view should answer:

- what is this run?
- what has it done?
- how expensive is it?
- what warnings exist?
- what can I do next?

## Inspecting Other Objects

The same drill-down pattern should later work for:

- team
- hosted agent
- session
- route
- task

So the console should feel like a small terminal UI system browser, not just one dashboard screen.

## Subagent Visibility

Subagents should not only appear in raw event text.

The operator view should surface them explicitly under the selected parent run.

For example:

- `subagents=2` in the run summary
- a collapsible section:
  - child name
  - child status
  - child turn count
  - child token usage later

This matters because otherwise delegation becomes hard to inspect.

## Slash Command Bar

Even with selection-based navigation, the bottom command line should remain.

It should support:

- `/help`
- `/runs`
- `/routes`
- `/sessions`
- `/teams`
- `/agents`
- `/inspect run <id>`
- `/inspect session <id>`
- `/cancel run <id>`
- `/pause agent <name>`
- `/rebind route <agent> <thread> <session>`

This gives expert operators a fast path without forcing every action through menus.

## Command Feedback

Operator commands should not fail silently.

Every control action should produce:

- visible success/failure feedback
- operator event log entry
- later audit record attribution

So if the operator types:

```text
/cancel run run_91ab
```

the console should show:

- command accepted
- pending / completed state later
- corresponding event in the event panel

## Key Bindings

The first terminal UX should likely use a small, memorable key set:

- `j` / `k` or arrow keys: move selection
- `Tab`: move between panels
- `Enter`: inspect selected item
- `q`: go back
- `/`: focus command line
- `r`: refresh
- `g`: go to top later
- `G`: go to bottom later

The key rule is:

- navigation should be possible without typing commands constantly

## Refresh Strategy

The first `ops` console should support two modes:

### 1. Polling Snapshot

Simple local refresh every N milliseconds.

Good first implementation.

### 2. Event-Aware Refresh

Later, refresh when:

- new operator event arrives
- run state changes
- route changes

That is more efficient and feels more realtime.

But polling is a good first slice for the terminal UI.

## Status And Color Language

The operator console should use a stable visual language:

- green = healthy / completed
- yellow = warning / nearing limits
- red = failed / blocked / cancelled
- blue = active / in progress
- gray = idle / archived

This matters a lot in dense terminal screens.

The operator should be able to scan the screen, not read every line.

## Context Pressure As First-Class UI

One important metric for agent systems is context pressure.

The operator console should show it explicitly as:

- percent
- maybe a small bar later

Examples:

- `ctx=24%`
- `ctx=61%`
- `ctx=92% WARN`

That is one of the most valuable live signals in an Agent OS.

It tells the operator:

- this run is nearing compaction
- or this run is still healthy

## Token Usage As First-Class UI

Likewise, token usage should not be hidden.

Per-run token usage should be visible because it tells the operator:

- cost pressure
- workload size
- possibly runaway behavior

Eventually, the console should support:

- current run token totals
- recent token rate
- team aggregate token usage

## Money As First-Class UI

Money should be visible next to token usage, not hidden in a later billing export.

Per-run cost should be visible because it tells the operator:

- whether a run is financially expensive
- whether a team is efficient
- whether a model/provider choice is appropriate

Eventually, the console should support:

- current run estimated cost
- aggregate cost by hosted agent
- aggregate cost by team
- cost over time windows later

The important design rule is:

- usage and price calculation happen in the execution core
- monitoring and the operator console only render and aggregate those values

## Pricing Source Of Truth

The operator console should not invent price numbers.

The source of truth should come from provider or model pricing configuration in the execution/runtime layer.

That means later the usage core should know:

- provider name
- model name
- input token price
- output token price
- pricing unit

And the operator UI should only display:

- estimated cost
- pricing profile used

This keeps cost logic centralized and testable.

## Threads, Sessions, Runs: Show All Three

The operator UI must keep these separate visually.

They are not the same thing.

At minimum:

- thread key identifies the external conversation stream
- session id identifies the harness continuity state
- run id identifies the concrete execution attempt

If the UI collapses them together, operators will become confused very quickly.

## Suggested First Screen Sequence

The first implementation path should probably be:

1. main dashboard
2. inspect run screen
3. inspect session screen
4. inspect route screen
5. first control action: cancel run

That is enough to prove the operator-console architecture before the full web/admin API work.

## Relationship To Web And Desktop

This terminal UX is only one presentation.

It should not define the data model.

Instead:

- the operator backend defines data contracts
- the terminal renders one dense text-first version
- later web and desktop can render the same state visually

This is why the dashboard is useful even at design time:

it forces us to decide what the backend must expose.

## Main Design Rule

The operator console should feel like a task manager for AgentOS:

- live
- dense
- keyboard-first
- drill-down friendly
- command-capable

And it should be built on top of one reusable operator backend surface, not a UI-specific pile of logic.

## The Three Parts Of The Operator Backend

At production level, the operator backend should have three clear parts:

### 1. Read Model

This is the query side.

It returns snapshots and details like:

- active routes
- recent runs
- run details
- session details
- team state
- task state
- background-service state

This side should be optimized for inspection.

### 2. Command Model

This is the control side.

It accepts commands like:

- cancel run
- pause agent
- disable team
- rebind route
- resume session
- drain queue
- later restart worker or service

This side should be explicit and auditable.

### 3. Event Stream

This is the realtime side.

It exposes:

- run started
- run finished
- route rebound
- background trigger fired
- worker stalled
- cancellation requested
- cancellation completed

This side is what later powers:

- live dashboards
- log tails
- realtime operator consoles

That gives us the clean operator pattern:

```text
query current state
send control command
subscribe to changing state
```

## Recommended First Types

The first clean backend shape should be:

- `OperatorService`
- `OperatorSnapshot`
- `OperatorCommand`
- later `OperatorEvent`
- later `OperatorStream`

That gives us a stable conceptual contract before we care about transport details.

## Operator Snapshots

The read model should return a snapshot that feels like a task manager.

At minimum, an operator snapshot should be able to include:

- routes
- runs
- sessions
- teams
- goals
- tasks
- queue depth
- recent failures

The first version does not need every field.

But it should be designed as one coherent snapshot, not many unrelated helper calls.

Why:

an operator view usually wants one consistent picture of the system at one moment in time.

## Read Operations

The read side should eventually expose things like:

- `list_agents()`
- `list_teams()`
- `list_routes()`
- `list_sessions()`
- `list_goals()`
- `list_tasks()`
- `list_runs()`
- `inspect_run(run_id)`
- `inspect_session(session_id)`
- `inspect_route(target_agent, thread_key)`
- `snapshot()`

The first implementation does not need all of them immediately.

But that is the right shape.

## Command Operations

The command side should be explicit and narrow.

That means no fuzzy “do something smart” admin endpoint.

Instead, use concrete commands like:

- `cancel_run(run_id)`
- `pause_agent(agent_name)`
- `resume_agent(agent_name)`
- `disable_team(team_id)`
- `enable_team(team_id)`
- `rebind_route(target_agent, thread_key, session_id)`
- `fork_session(session_id)`
- `archive_session(session_id)`

This matters because operator actions are higher-risk than user chat messages.

They should be:

- validated
- logged
- attributable

## Operator Events

The event stream should be separate from the read model.

The read model answers:

- what is true now?

The event stream answers:

- what just changed?

That distinction is important.

A good event stream later makes it possible to:

- refresh a dashboard cheaply
- follow one run live
- notify when a background service fails
- trace route changes

## Data Sources Behind The Operator Service

The operator backend should not own all state itself.

It should aggregate from the existing OS components:

- `AgentRegistry`
- `TeamRegistry`
- `RouteStore`
- `SessionStore`
- `GoalStore`
- `TaskStore`
- `RunStore`
- `MessageBus`
- later background service registries

That means the operator layer is an orchestrator and aggregator, not a new database.

## Suggested Internal Architecture

The backend shape should feel like this:

```text
operator service
  -> registry readers
  -> route/session readers
  -> run/task/goal readers
  -> live runner/bus observers
  -> control executors
```

The control executors are the important part.

They are where high-risk actions should be validated and logged.

## Why This Should Not Live Inside The Runner

It may be tempting to keep all admin logic inside the runner.

That is the wrong shape.

The runner’s job is:

- take one envelope
- resolve route and runtime
- execute one turn
- persist results

The operator service’s job is different:

- inspect many runs
- inspect many sessions
- coordinate control actions
- aggregate state across the whole system

So:

- runner is execution
- operator service is administration

Keep them separate.

## Permissions And Safety

At production level, the operator side should eventually distinguish at least two permission levels:

### Observer

Can:

- inspect routes
- inspect runs
- inspect sessions
- inspect recent events

Cannot:

- cancel
- pause
- rebind
- disable

### Controller

Can:

- inspect
- cancel
- pause
- rebind
- disable

This matters even on a local machine, because later the same backend will be exposed over remote APIs.

The permission model should be part of the design early, even if the first local CLI skips authentication.

## Control Actions Must Be Audited

Every operator control action should later produce an operator event and an audit record.

Examples:

- `cancel_run requested`
- `cancel_run completed`
- `route rebound`
- `team disabled`

That matters for exactly the same reason tracing matters:

if a human changes system state, we need to know:

- who did it
- when
- why

## Realtime Monitoring

Once we have a dedicated operator surface, the next requirement becomes obvious:

the operator console should support live refresh or streaming updates.

That means the operator backend should later expose:

- polling-friendly snapshots
- and/or event streams

Examples:

- recent runs changed
- route rebound
- background service triggered
- run failed
- run cancelled

That is what will later make a realtime admin dashboard possible.

## Single Machine vs Multi Machine

The operator design should already support both deployment shapes conceptually.

### Single Machine

- work console and operator console talk to the same local OS state
- the operator service can read local files and in-process registries

### Multi Machine

- work console still talks to one front-door system
- operator console still talks to one operator API
- backend may fan out to remote workers over ACP or other gateways

This is another reason not to bake monitoring logic into the user CLI.

The operator surface should be transport-neutral.

## Transport Evolution

The same backend should later be exposable through:

- local in-process calls
- local socket
- HTTP
- WebSocket
- gRPC
- maybe ACP-facing management surfaces later

The transport should not change the operator data model.

This is the production-level rule:

define the operator service first, choose transport second.

## Terminal Model

The split should feel like this:

### Terminal 1: Work

```text
make cli
```

Use it to:

- chat with `superagent`
- review outputs
- approve plans

### Terminal 2: Control

```text
make ops
```

Use it to:

- inspect runs
- inspect routes
- inspect sessions
- inspect teams
- later cancel or pause active work

That is a much more realistic operating model.

## Current Scaffold vs Target Shape

Today, the project already has tiny pieces of this inside the main CLI:

- `/routes`
- `/runs`
- `/session`
- `/sessions`

Those are useful as early scaffolding.

But the long-term target should be:

- the work console stops owning operator views
- the operator console becomes the real admin surface
- both are backed by one operator service

## First Implementation Slice

The first real slice in this project is intentionally smaller than the full target design.

It now includes:

1. `OperatorService`
2. a separate `make ops` entrypoint
3. a Textual dashboard with:
   - summary
   - teams
   - runs
   - agents
   - routes
   - sessions
   - alerts
4. `/inspect run <id>` in the operator console command bar
5. token, context, and estimated-cost monitoring in run summaries

That is enough to validate the architecture:

- one operator backend
- one dedicated operator presentation
- one place to aggregate monitoring data

It is **not** yet the full control plane for operators.

Still missing after the first slice:

- cancel and pause commands
- live event drill-down per run
- task and goal panels
- background-service panels
- permissions and multi-user operator roles

That is a disciplined first milestone.

It proves the split works without pretending we already have a full production dashboard.

## Main Design Rule

The work console is for one conversation.

The operator console is for the system.

Do not mix them.

Keep both backed by the same Agent OS runtime and the same operator backend surface.

That is what will let this project grow naturally into:

- richer local operator tooling
- web dashboards
- desktop applications
- external administration APIs

without rewriting the core design.
