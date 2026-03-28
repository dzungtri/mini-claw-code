# Chapter 42: ACP Gateway and Session Modes

ACP belongs at the Agent OS boundary.

It is not a harness feature.

It is a protocol and gateway feature.

## Why ACP Matters

ACP gives us:

- structured sessions
- structured updates
- client capabilities
- session config options
- mode switching

That makes it a strong fit for:

- editor integrations
- remote agent hosting
- cross-process agent communication

## Requirements

The first ACP gateway should:

- create sessions
- select a target agent
- forward prompts into the OS runner
- stream harness events back out
- support session config options like:
  - mode
  - model

It does **not** need:

- multi-node discovery
- federation
- distributed team orchestration

## Architecture

The first shape should include:

- `ACPGateway`
- `ACPClientSession`
- `ACPConfigOptions`

The important design rule is:

- ACP creates and controls sessions
- the runner executes turns
- the harness remains the execution engine

So ACP wraps the OS.

It does not replace it.
