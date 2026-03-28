# Chapter 39: Teams, Goals, Tasks, and Runs

By Chapter 38, the OS can host named agents.

That is still not enough to operate a real multi-agent system.

We also need a state model for work.

Without that, the OS only knows:

- a message arrived
- an agent exists

It does **not** know:

- what larger goal the work belongs to
- which team owns that goal
- which member is responsible for which task
- which concrete execution attempt produced a result

That is what this chapter adds.

## What We Are Building

The first slice should stay small and local:

- a file-defined team registry
- a goal store
- a task store
- a run store

All of them should be local and file-backed.

That keeps the model visible and testable before we wire it into routing and runners.

## The Hierarchy

The OS should think in this order:

```text
thread
  -> goal
     -> team
        -> task
           -> run
```

Each layer answers a different question:

- `thread`: where the conversation came from
- `goal`: what the user ultimately wants
- `team`: which execution group owns the work
- `task`: which unit of work was assigned
- `run`: which concrete execution attempt happened

This is why Chapter 39 belongs **above** session routing.

Sessions preserve harness continuity.

Goals, tasks, and runs preserve OS coordination.

## Teams First

We need a team registry before we create goals.

The first team registry should use `.teams.json`.

Example:

```json
{
  "teams": {
    "product-a": {
      "description": "Primary software delivery team for product A.",
      "lead_agent": "superagent",
      "member_agents": ["backend-dev", "frontend-dev", "tester"]
    },
    "marketing": {
      "description": "Marketing planning and content team.",
      "lead_agent": "marketing-lead",
      "member_agents": ["copywriter", "seo-agent"]
    }
  }
}
```

The first team fields should stay small:

- `description`
- `lead_agent`
- `member_agents`

That is enough to support goal assignment and future operator views.

## Built-In Default Team

Just like the Agent OS always needs a default `superagent`, it also needs one built-in team.

If no `.teams.json` exists, the system should still expose:

- `default`
- `lead_agent = "superagent"`
- `member_agents = ["superagent"]`

Why:

- `make cli` should keep working in a new repository
- the OS should have one general-purpose execution group before teams are customized

## Goals

A goal is the top-level objective.

Examples:

- build feature A
- investigate failing tests
- create launch copy for a product page

The first goal record should include:

- `goal_id`
- `title`
- `description`
- `primary_team`
- `status`
- `created_at`
- `updated_at`

The first status set should stay simple:

- `pending`
- `in_progress`
- `blocked`
- `completed`

For the first implementation, one goal belongs to one primary team.

That is a deliberate scope limit.

Cross-team goals can come later.

## Tasks

A task is a team-level unit of work assigned to one hosted agent.

Examples:

- backend-dev implements endpoint changes
- tester reproduces a bug
- copywriter drafts landing-page text

The first task record should include:

- `task_id`
- `goal_id`
- `team_id`
- `agent_name`
- `title`
- `status`
- `created_at`
- `updated_at`

It may later grow richer fields like:

- `description`
- `depends_on`
- `priority`
- `labels`

But the first slice should not start there.

## Runs

A run is one concrete execution attempt of one task.

This is the most important operator-facing unit.

The first run record should include:

- `run_id`
- `task_id`
- `agent_name`
- `session_id`
- `trace_id`
- `status`
- `started_at`
- `finished_at`

For runs, the first status set should be:

- `running`
- `completed`
- `failed`
- `cancelled`

This is intentionally different from goal/task status.

Goals and tasks describe work state.

Runs describe execution attempts.

## Why Runs Matter So Much

Later chapters will add:

- session routing
- turn runners
- bus-driven execution
- ACP and channels
- traceability and operator controls

All of those need one stable execution record.

That record is the run.

If an operator wants to know:

- what happened
- where it ran
- which session it used
- which trace to inspect

the run store should be the first place to look.

## Storage Layout

The first local shape should be:

```text
.mini-claw/
  os/
    goals.json
    tasks.json
    runs.json
```

And the team registry should stay near the workspace root:

```text
.teams.json
```

Why split them this way:

- `.teams.json` is operator/project configuration
- `.mini-claw/os/*.json` is live runtime state

That mirrors the split we already use elsewhere:

- config files define the system
- `.mini-claw/` stores runtime state

## Required First-Slice Operations

The first stores should support:

### Team Registry

- discover user + project `.teams.json`
- field-wise merge
- built-in default team

### Goal Store

- create goal
- load goal
- list goals
- update status

### Task Store

- assign task
- load task
- list tasks
- filter by goal or team
- update status

### Run Store

- start run
- finish run
- load run
- list runs
- filter by task

That is enough to support the next chapters cleanly.

## What We Intentionally Skip

The first slice should **not** implement:

- multi-team goals
- cross-goal dependencies
- distributed locking
- background retries
- task priority scheduling
- SLA management
- agent utilization balancing

Those are real concerns, but they are not the first backbone.

## Runtime Surface

The early CLI should at least be able to show:

- discovered teams
- current goal/task/run tables later

For this chapter, team visibility is enough.

We do not need a full operator dashboard yet.

## Main Design Rule

Keep coordination state separate from harness state.

That means:

- goal/task/run stores should not live inside `HarnessAgent`
- session state should not be reused as task state
- one run may use one session, but they are not the same object

That separation will matter more and more in the next chapters.

## Implementation Target

The first concrete slice should introduce:

- `TeamDefinition`
- `TeamRegistry`
- `GoalRecord`
- `TaskRecord`
- `RunRecord`
- `GoalStore`
- `TaskStore`
- `RunStore`

And it should give the TUI one simple operator surface:

- `/teams`

That gives us a visible coordination backbone before we add session routing and bus-driven execution.
