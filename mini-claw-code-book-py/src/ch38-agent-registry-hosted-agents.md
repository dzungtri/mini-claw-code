# Chapter 38: Agent Registry and Hosted Agents

In Chapter 37, the OS learned how to move normalized envelopes through a bus.

That still leaves one important question:

When a message targets `superagent` or `pipi`, what exactly is that thing?

The answer is not a live Python object sitting inside a global map.

The answer is an agent registry.

## What We Are Building

We want a small registry that can answer three questions:

1. Which hosted agents exist?
2. What runtime roots belong to each one?
3. How does the OS build a fresh `HarnessAgent` for a named hosted agent?

The first implementation should stay local and simple:

- file-defined hosted agents
- user + project registry merge
- one built-in default `superagent`
- a factory that builds a fresh harness runtime on demand

## Hosted Agents Are Not Subagents

This distinction must stay sharp.

Subagents are:

- short-lived
- created inside one harness turn
- owned by a parent agent
- discarded after the task finishes

Hosted agents are:

- named OS identities
- discoverable by the registry
- routable by the OS
- able to own many sessions over time

So the registry is not a replacement for subagent profiles.

It is the directory of top-level agent identities that the OS knows how to host.

## The First Concrete Shape

For this project, the first registry will use `.agents.json`.

It follows the same design style as `.mini-claw.json`, `.mcp.json`, and `.subagents.json`.

Example:

```json
{
  "agents": {
    "superagent": {
      "description": "Default front-door agent for CLI and operator requests.",
      "workspace_root": ".",
      "default_channels": ["cli"]
    },
    "reviewer": {
      "description": "Use for repository review and bug finding.",
      "workspace_root": ".",
      "config_path": ".mini-claw-review.json",
      "default_channels": ["bus"]
    }
  }
}
```

The first slice keeps the fields narrow:

- `description`
- `workspace_root`
- `default_channels`
- optional `config_path`
- optional `remote_endpoint`

That is enough to build a useful hosted-agent registry without dragging in team, ACP, or remote execution too early.

## Why `config_path` Matters

The registry should not duplicate the whole harness config surface.

That would create two configuration systems:

- the harness config
- the hosted-agent config

That is the wrong direction.

Instead, the registry should only answer:

Which harness config source should this hosted agent use?

So `config_path` means:

- use the normal harness config loader
- but let this hosted agent point at a different concrete `.mini-claw.json` file if needed

That keeps the boundary clean:

- registry decides identity
- harness config decides runtime behavior

## Merge Rules

The registry should search:

1. user-level `.agents.json`
2. project-level `.agents.json`

And it should merge them in that order.

The merge rule should be field-wise:

- project overrides user when a field is present
- absent fields inherit
- lists replace lists

Example:

User file:

```json
{
  "agents": {
    "reviewer": {
      "description": "General review agent",
      "workspace_root": ".",
      "default_channels": ["bus", "cli"]
    }
  }
}
```

Project file:

```json
{
  "agents": {
    "reviewer": {
      "description": "Project-specific review agent"
    }
  }
}
```

Effective result:

- `description` comes from the project file
- `workspace_root` and `default_channels` still come from the user file

Whole-object replacement would be a footgun here.

## Built-In Default `superagent`

The registry should always expose a local `superagent`.

If no file defines it, the runtime should synthesize one:

- `name = "superagent"`
- `workspace_root = current cwd`
- `default_channels = ["cli"]`
- `description = "Default front-door hosted agent."`

Why:

- `make cli` should keep working even in a new repository
- the Agent OS should always have one obvious front door

Later chapters may let the project override or replace that definition, but the first implementation should never leave the OS without a hosted front-door agent.

## Factory, Not Singleton

The registry should not hold live `HarnessAgent` instances.

It should hold buildable definitions.

The runtime contract should look like this:

```python
definition = registry.require("superagent")
agent = factory.build(definition)
```

That is better than caching one long-lived Python object because it keeps the next chapters simpler:

- Chapter 40 will restore session state into a fresh runtime
- Chapter 41 will run turns from the bus by constructing a runtime for the target agent

So hosted agents are definitions first, runtimes second.

## What The Factory Should Reuse

The first factory should reuse the same harness assembly path we already trust in the CLI:

1. load prompt template
2. render system prompt for the target workspace
3. create `HarnessAgent`
4. load harness config for that hosted agent
5. apply the harness config

This matters because we do **not** want two different ways to build a harness runtime:

- one for CLI
- another for Agent OS

The Agent OS path should wrap the harness path, not fork it.

## Runtime Surface

The first runtime surface should be small but visible.

When the user runs the CLI, the app should be able to show:

- which hosted agents were discovered
- which one is currently active
- which workspace root each one uses

That is enough for the early OS chapters.

We do not need:

- health checks
- remote reachability probes
- live worker pools

Not yet.

## What We Intentionally Skip

The first registry should **not** solve:

- team definitions
- agent-to-agent routing
- remote ACP transport
- dynamic service discovery
- live runtime caching
- long-lived worker supervision

Those belong to later Agent OS chapters.

## The Main Design Rule

Keep the registry small and declarative.

The registry should say:

- this agent exists
- here is its workspace root
- here is the harness config source used to build it

It should not try to become:

- a runner
- a scheduler
- a health monitor
- a team manager

That is how the architecture stays understandable.

## Implementation Target

The first concrete slice should introduce:

- `HostedAgentDefinition`
- `HostedAgentRegistry`
- `HostedAgentFactory`

And it should let the TUI keep working by building the default `superagent` through the registry.

That gives us a stable hosted-agent backbone before we move on to teams, task state, and session routing.
