# Chapter 39: Teams, Goals, Tasks, and Runs

If the OS can host many agents, it still needs one more thing:

organization.

Without that, a multi-agent system becomes a random graph of messages.

## The Goal

We want the OS to support:

- one front-door `superagent`
- one or many backend teams
- one or many goals running at the same time

That means we need a stronger state model.

## The Hierarchy

The cleanest hierarchy is:

```text
user thread
  -> goal
     -> team
        -> tasks
           -> runs
```

## Definitions

### Goal

The top-level objective.

Examples:

- build feature A
- launch campaign B
- investigate incident C

### Team

The execution group responsible for one area.

### Task

A unit of work assigned to one agent.

### Run

One execution attempt of a task.

## Requirements

The first team model should:

- allow one `superagent` to create goals
- assign each goal to one team
- let team leads create member tasks
- track task status
- support later UI views

Statuses should stay simple:

- `pending`
- `in_progress`
- `blocked`
- `completed`

## Architecture

The first OS state stores should include:

- `GoalStore`
- `TeamRegistry`
- `TaskStore`
- `RunStore`

The key contracts are:

```python
goal_id = goal_store.create(...)
task_store.assign(goal_id=goal_id, team_id="product-a", agent_name="frontend-dev", ...)
```

This gives the OS a management model, not just a transport model.
