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
- better operator visibility into remote sessions

That makes it a strong fit for:

- editor integrations
- remote agent hosting
- cross-process agent communication

## Requirements

The first real gateway slice should:

- create sessions
- select a target agent
- forward prompts into the OS runner
- stream harness events back out
- support session config options like:
  - mode
  - model
- preserve session and trace identity across the protocol boundary

For the first implementation, we can keep one deliberate scope limit:

- build an in-process gateway service first
- keep ACP as the next protocol transport over that same service

For the first version, the gateway should target one hosted agent per session.

That keeps the mapping clean:

- ACP session -> target agent -> session router -> harness session
- gateway session -> target agent -> session router -> harness session

It does **not** need:

- multi-node discovery
- federation
- distributed team orchestration

## ACP vs The Internal Bus

ACP should not replace the internal OS bus.

The clean split is:

- local in-process coordination: internal bus and stores
- remote/editor/network coordination: ACP gateway

That means:

- `make cli` on the same machine can stay on the local path
- remote tools, remote nodes, and editor integrations can speak ACP

This is the same pattern we saw in the reference systems:

- DeepAgents uses ACP at the editor / remote-session boundary
- Mimiclaw uses a gateway and a local bus as different layers

That is the architecture we should keep.

## First Concrete Slice

The first implemented gateway path should look like:

```text
gateway session
  -> MessageEnvelope
  -> MessageBus inbound queue
  -> TurnRunner.run_from_bus()
  -> HarnessAgent
  -> outbound envelope + run record + session update
```

This gives us two real execution paths to test:

- direct local path
  - `make cli -> TurnRunner.run(envelope)`
- gateway-mediated path
  - `GatewayService -> bus -> TurnRunner.run_from_bus()`

That is enough to validate the network backbone before we add a remote transport.

## Authentication And Trust

Once ACP or any gateway crosses the network, authentication becomes mandatory.

The first network-safe rules should be:

- always run over TLS
- authenticate the remote client or node
- never trust inbound `agent_name`, `thread_key`, or `session_id` blindly
- map authenticated identity to allowed target agents and allowed channels
- audit every mode switch and remote control action

The simplest production-minded evolution is:

- local dev mode: no remote gateway yet
- first remote mode: bearer token or signed service token over TLS
- stronger production mode: mutual TLS plus signed node / client identity

## Session Modes And Model Switching

ACP is also the right place for session-level switches such as:

- mode
- model
- maybe later operator approval state

That matches the DeepAgents ACP examples well:

- the protocol creates the session
- the gateway updates session config
- the runner builds the harness turn using that resolved config

So session config belongs at the gateway boundary, not hidden inside the TUI.

For the first implementation, `mode` and `model` may be stored as gateway session config before they fully influence the runtime builder.

That is still valuable because it establishes:

- the session config boundary
- the persistence model
- the future transport contract

In the first local slice, the gateway should also normalize empty mode values back to `default`.

That keeps the session contract stable even before we add richer protocol validation.

## Architecture

The first shape should include:

- `GatewaySession`
- `GatewaySessionStore`
- `GatewayService`
- later `ACPGateway`
- later `ACPClientSession`
- later richer `ACPConfigOptions`

The important design rule is:

- ACP creates and controls sessions
- the runner executes turns
- the harness remains the execution engine

The current implemented path also reuses the same routed harness session across multiple messages in one gateway session.

That means:

- gateway session identity stays stable
- routed harness `session_id` stays stable
- front-door task binding stays stable

So ACP wraps the OS.

It does not replace it.
