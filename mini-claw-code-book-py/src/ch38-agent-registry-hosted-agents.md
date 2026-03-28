# Chapter 38: Agent Registry and Hosted Agents

Once the OS can accept normalized messages, it needs to know:

- what agents exist
- how each agent is configured
- how to build each runtime

That is the job of the agent registry.

## The Goal

We want the OS to host many named agents:

- `superagent`
- `pipi`
- `reviewer`
- `marketing-lead`

Each one should be a first-class runtime identity.

## Why This Is Different From Subagents

Subagents are temporary delegated workers inside one harness turn.

Hosted peer agents are long-lived identities managed by the OS.

They may:

- own sessions
- own memory
- own skills
- own MCP config
- own policy profiles

So the OS needs a registry, not just a prompt section.

## Required Fields

Each agent definition should include:

- `agent_name`
- `description`
- `harness_profile`
- `memory_root`
- `workspace_root`
- `default_channels`

Optional fields:

- `skills`
- `mcp`
- `subagents`
- `control_profile`
- `remote_endpoint`

Here `harness_profile` should mean:

- either a named runtime profile
- or a pointer to a concrete harness config source

The important design rule is that the agent registry does not store a live runtime object.

It stores the information needed to build one.

## Requirements

The first registry should:

- support one local `superagent`
- support several local peer agents
- allow simple file-defined registration
- return a runnable `HarnessAgent` factory for each definition

It does **not** need:

- dynamic service discovery
- distributed consensus
- remote health management

## Architecture

The first shape should be:

- `AgentDefinition`
- `AgentRegistry`
- `AgentFactory`

The key contract is:

```python
definition = registry.get("pipi")
agent = agent_factory.build(definition)
```

That gives the OS a clean way to host many harness runtimes without turning `HarnessAgent` itself into an OS.
