# Chapter 14: MCP: Model Context Protocol

By Chapter 13 your agent can call built-in tools, plan, stream, and even spawn
subagents. That's enough to build a serious coding agent -- but it still has one
big limitation: every capability must be compiled into your binary ahead of time.

Real agents outgrow that quickly. You want one server that talks to GitHub,
another that exposes your issue tracker, another that serves project docs, and
maybe a private internal tool that only your team uses. Recompiling your agent
for every integration is the wrong abstraction.

**MCP** fixes this. The **Model Context Protocol** is a standard way for an
agent to discover tools and resources from external servers. Instead of baking
those integrations into your core crate, you connect to an MCP server, ask what
it offers, and expose those capabilities to the model.

This is how modern coding agents stay extensible. Claude Code, OpenCode, and
similar tools all use the same core idea: **the agent loop stays the same; only the tool source changes**.

In this chapter you'll design the MCP layer for `mini-claw-code`, borrowing the
core ideas from the Rust reference implementation in:

- `crates/runtime/src/mcp.rs`
- `crates/runtime/src/mcp_client.rs`
- `crates/runtime/src/mcp_stdio.rs`

You will:

1. Normalize MCP tool names so remote tools fit cleanly into your existing
   `ToolDefinition` model.
2. Separate **transport bootstrap** from **agent-facing tool exposure**.
3. Use JSON-RPC over stdio as the simplest transport to start with.
4. Discover remote tools and index them by a qualified name.
5. Treat MCP resources as a parallel read-only data surface.
6. Keep MCP purely additive -- no rewrite of `SimpleAgent` required.

## Why MCP?

Suppose your agent already has `read`, `write`, and `bash`, and now you want it
to answer questions like:

- "What's the status of PR #241?"
- "Read the design doc from our internal knowledge base"
- "Create a Jira ticket for this bug"

You *could* build `github`, `jira`, and `docs_search` as first-party tools.
That works for one project. It does not scale.

MCP gives you a better boundary:

```text
Agent loop
  ↓
Built-in tools (read, write, bash)
  +
Remote MCP tools (github, jira, docs, ...)
```

Your agent does not need to know how GitHub auth works, or how your docs system
stores pages. It only needs a standard protocol for:

1. **discovering** tools
2. **calling** tools
3. **listing** resources
4. **reading** resources

That is the mental model: **MCP is for external capabilities what `ToolSet` is
for local capabilities.**

## Namespacing remote tools

The first design problem is naming.

Your local tools are simple: `read`, `write`, `bash`.

MCP servers are not. Two different servers might both export a tool named
`search`. If you flatten those into one namespace, collisions are inevitable.

The Rust reference solves this in `runtime/src/mcp.rs` with three helpers:

```rust
normalize_name_for_mcp("github.com") -> "github_com"
mcp_tool_prefix("github.com")       -> "mcp__github_com__"
mcp_tool_name("github.com", "search issues")
    -> "mcp__github_com__search_issues"
```

That prefix is the key idea. The agent never sees a raw remote tool name like
`search issues`. It sees a fully qualified tool name such as:

```text
mcp__github_com__search_issues
```

This buys you three things immediately:

- **No collisions** between servers
- **Deterministic routing** back to the correct server/tool pair
- **Predictable tool names** for the LLM

In a mini implementation, the routing table can be as small as:

```rust
struct ToolRoute {
    server_name: String,
    raw_name: String,
}

let qualified = mcp_tool_name(server_name, &tool.name);
tool_index.insert(qualified, ToolRoute {
    server_name: server_name.to_string(),
    raw_name: tool.name.clone(),
});
```

Once you have this, an MCP tool call looks just like any other tool call from
the model's point of view.

## Bootstrap first, tools second

The reference implementation makes another important separation.

Before the agent can *use* an MCP server, it has to know **how to reach it**.
That is bootstrap data: command-line args, environment, URL, auth settings,
transport kind, and a stable server signature.

In `runtime/src/mcp_client.rs`, that data is captured in `McpClientBootstrap`
and `McpClientTransport`.

A simplified version looks like this:

```rust
pub enum McpClientTransport {
    Stdio { command: String, args: Vec<String> },
    Http  { url: String },
    Sse   { url: String },
    WebSocket { url: String },
}

pub struct McpClientBootstrap {
    pub server_name: String,
    pub normalized_name: String,
    pub tool_prefix: String,
    pub transport: McpClientTransport,
}
```

Why split bootstrap from discovered tools?

Because they answer different questions:

- **Bootstrap**: "How do I start or connect to this server?"
- **Discovery**: "What tools and resources does this server provide right now?"

That separation keeps your design honest. Starting a process and listing tools
are not the same concern.

## Start with stdio

MCP supports several transports, but **stdio** is the best first step for a
book-sized agent.

Why stdio?

- It's local and easy to reason about.
- You can spawn a child process with `tokio::process::Command`.
- The request/response boundary is explicit.
- You don't need to teach sockets, retries, or reconnect logic yet.

That is exactly what the reference implementation does in
`runtime/src/mcp_stdio.rs`: it starts with a `McpStdioProcess` that speaks
JSON-RPC over stdin/stdout.

The protocol shape is simple:

```text
Agent                MCP server
  |  initialize  --> |
  | <-- result       |
  |  tools/list -->  |
  | <-- tools        |
  |  tools/call -->  |
  | <-- result       |
```

The important detail is that the MCP process is **stateful**. After you spawn
it, you usually keep it alive, initialize it once, and then reuse it for later
requests.

That is why the reference manager stores both:

- the process handle
- an `initialized: bool` flag

## JSON-RPC is the wire format

Inside the transport, MCP is just JSON-RPC messages.

The reference code defines plain Rust structs for requests and responses:

```rust
pub struct JsonRpcRequest<T = JsonValue> {
    pub jsonrpc: String,
    pub id: JsonRpcId,
    pub method: String,
    pub params: Option<T>,
}

pub struct JsonRpcResponse<T = JsonValue> {
    pub jsonrpc: String,
    pub id: JsonRpcId,
    pub result: Option<T>,
    pub error: Option<JsonRpcError>,
}
```

This is worth copying exactly in spirit, even if your first implementation is
small.

Why? Because once the request/response layer is typed, the higher-level MCP
manager becomes mostly boring plumbing:

- send `initialize`
- send `tools/list`
- send `tools/call`
- parse typed responses
- return normal Rust values upward

That is what you want. Protocol code should be boring.

## Discovering tools

The core runtime object in the reference implementation is `McpServerManager`.
It owns:

- the configured servers
- the currently running stdio processes
- a `tool_index` mapping qualified names to routes
- a monotonically increasing request id

Its `discover_tools()` method does the real work:

1. Ensure the server process exists
2. Initialize it if needed
3. Call `tools/list`
4. Qualify each tool name with the server prefix
5. Store a route in `tool_index`
6. Return the discovered tools to the caller

That is the bridge between the external protocol and your internal `ToolSet`
world.

A useful mini representation is:

```rust
pub struct ManagedMcpTool {
    pub server_name: String,
    pub qualified_name: String,
    pub raw_name: String,
    pub tool: McpTool,
}
```

Now you can turn each discovered MCP tool into something your LLM already
understands:

```rust
ToolDefinition {
    name: qualified_name,
    description: tool.description,
    parameters: tool.input_schema,
}
```

That is the big win: **MCP tools become ordinary tool definitions at the edge
of the agent loop.**

`SimpleAgent` does not need a special "remote tool mode." It still just sends a
tool list to the provider and receives a tool call back.

## Calling a remote tool

Once discovery has populated `tool_index`, tool execution is just a lookup.

```rust
pub async fn call_tool(
    &mut self,
    qualified_tool_name: &str,
    arguments: Option<JsonValue>,
) -> Result<JsonRpcResponse<McpToolCallResult>, McpServerManagerError>
```

The qualified name tells you which server to use. The route gives you the raw
MCP tool name. Then you forward the call with `tools/call`.

This is exactly the same pattern as `ToolSet::get(name)` in earlier chapters:

- local tools: name → boxed tool object
- MCP tools: qualified name → server/process + raw tool name

Different storage, same idea.

## Resources are not tools

MCP has another surface besides tools: **resources**.

A resource is usually something the model should read rather than execute:

- a document
- a schema
- a config object
- a dataset handle

The reference implementation exposes both `resources/list` and `resources/read`
request types. That is a strong design signal: resources deserve their own
path.

Do not force everything into a tool call.

A clean mental model is:

- **Tools** do work
- **Resources** provide context

In a future `mini-claw-code` implementation, you could expose MCP resources in
at least two ways:

1. As explicit tools like `mcp__docs__read_resource`
2. As a pre-step that lets your app read resources and inject them into the
   prompt

Both are valid. The important thing is not to blur the distinction.

## Error handling and unsupported transports

The reference implementation is deliberately conservative.

`McpServerManager` currently supports stdio directly and records other
transports as `UnsupportedMcpServer` entries. That is a good incremental design.
It means you can parse full config up front without pretending you implemented
all transports on day one.

The error enum is similarly practical:

- I/O failures when spawning or talking to the process
- JSON-RPC errors returned by the server
- invalid/malformed responses
- unknown tool names
- unknown server names

This matters because MCP failures are not all the same.

```text
unknown tool       -> routing/config bug
JSON-RPC error     -> server understood request but rejected it
I/O error          -> process/transport failure
invalid response   -> protocol mismatch or buggy server
```

Keep those cases separate. When external systems are involved, good errors are
half the feature.

## Wiring MCP into the agent

The cleanest integration point is *outside* `SimpleAgent`.

One workable design is:

1. Build your normal local `ToolSet`
2. Ask `McpServerManager` for discovered MCP tools
3. Convert them into `ToolDefinition`s for the model
4. When the model calls a qualified MCP tool name, route it back through the
   manager

In other words, add a thin adapter layer:

```text
LLM tool call
   ↓
qualified name starts with mcp__ ?
   ├─ no  -> local ToolSet
   └─ yes -> McpServerManager::call_tool(...)
```

That adapter is the entire integration story.

The agent loop from Chapter 5 does not fundamentally change. The LLM still:

1. receives tool definitions
2. chooses a tool
3. gets a tool result back
4. continues the loop

MCP extends the agent by **adding a new tool source**, not by inventing a new
control flow.

## What to implement first

If you build this for real, keep the first version small:

1. **stdio only**
2. **initialize + tools/list + tools/call**
3. **qualified tool names** via `mcp__server__tool`
4. **tool index** for routing
5. **typed JSON-RPC structs**
6. **clear error types**

That already gets you a usable MCP bridge.

Leave these for later:

- HTTP/SSE/WebSocket transports
- OAuth helpers
- automatic reconnects
- caching discovery results
- resource prefetching

The reference runtime supports a wider world. Your mini agent does not need to
start there.

## Running the design review

For a chapter like this, the verification target is architectural rather than
behavioral. Before you start coding, make sure your design can answer these
questions cleanly:

- How are remote tool names namespaced?
- Where is server bootstrap config stored?
- Which layer owns JSON-RPC framing?
- Where is the tool routing table kept?
- How do resource reads differ from tool calls?
- Which errors are transport failures vs protocol failures?

If you can answer all six without hand-waving, your design is probably ready to
implement.

## Recap

- **MCP** lets your agent discover tools and resources from external servers.
- **Qualified tool names** like `mcp__github__search_issues` prevent collisions
  and make routing deterministic.
- **Bootstrap** (how to connect) is a separate concern from **discovery** (what
  the server exposes).
- **stdio + JSON-RPC** is the cleanest first transport for a tutorial agent.
- **`McpServerManager`** is the bridge: initialize server, list tools, index
  routes, forward calls.
- **Resources are not tools** -- keep read-only context separate from active
  execution.
- **Purely additive**: MCP should extend your tool surface without rewriting the
  core agent loop.
