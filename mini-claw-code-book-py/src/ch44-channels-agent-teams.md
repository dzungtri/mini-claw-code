# Chapter 44: Channels and Agent Teams

By Chapter 43, the Agent OS can already route front-door work, create goals and tasks, and run background turns.

But the outside world still needs a clearer model.

We need to answer two practical questions:

- how does a user-facing surface decide which hosted agent receives a turn?
- how do we describe team ownership and workspace boundaries without hardcoding everything in one app?

This chapter introduces that missing layer:

- channel definitions
- team workspace metadata
- a cleaner front-door rule for `make cli`

## The Goal

We want the OS to support:

- one or many user-facing channels
- one or many hosted agents
- one or many teams

But normal user traffic should still feel simple:

- a channel resolves to one front-door target
- that target usually becomes a hosted lead agent
- the lead agent drives team work behind the scenes

The user should not need to know every backend agent name.

## The First Practical Rule

The first slice stays intentionally conservative:

- channels define where a front door points
- teams define who owns a domain and which workspace they use
- `make cli` resolves itself through the `cli` channel definition

This means the work console no longer needs to hardcode:

- `target_agent = "superagent"`
- `thread_key = "cli:local"`

Instead, it can ask the channel layer what the front-door route should be.

## Channel Definitions

For the tutorial, a channel definition is a small declarative object:

- `name`
- `description`
- `default_target_agent` or `default_team`
- `thread_prefix`

The current implementation lives in:

- [`channels.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/channels.py)

The configuration file is:

- `.channels.json`

Example:

```json
{
  "channels": {
    "cli": {
      "description": "Local front-door terminal channel.",
      "default_target_agent": "superagent",
      "thread_prefix": "cli"
    },
    "telegram": {
      "description": "Telegram support channel.",
      "default_team": "support",
      "thread_prefix": "tg"
    }
  }
}
```

### Why `default_target_agent` and `default_team` both exist

Both are useful:

- `default_target_agent`
  Good when the route is obvious and stable.
- `default_team`
  Good when the channel concept belongs to a team, and the lead agent may change later.

If a channel uses `default_team`, the runtime resolves the lead agent from the team registry.

That lets the routing rule stay stable even if the lead changes.

## Team Definitions

By Chapter 39 we already had:

- `lead_agent`
- `member_agents`
- description

In this chapter, we add one more important field:

- `workspace_root`

The current implementation lives in:

- [`work.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/work.py)

Example:

```json
{
  "teams": {
    "product-a": {
      "description": "Software delivery team for Product A.",
      "lead_agent": "superagent",
      "member_agents": ["backend-dev", "frontend-dev", "qa-agent"],
      "workspace_root": "repos/product-a"
    },
    "marketing": {
      "description": "Marketing and launch team.",
      "lead_agent": "marketing-lead",
      "member_agents": ["copywriter", "seo-agent"],
      "workspace_root": "workspaces/marketing"
    }
  }
}
```

## Why Team Workspace Metadata Matters

This field is not only cosmetic.

It captures an important Agent OS rule:

- teams should usually have separate primary workspaces

That gives us a better mental model:

- one software team may collaborate in one repository root
- another team may work in a marketing workspace
- different teams should not blindly mutate the same root by default

For this chapter, the value is metadata and visibility first.

Later chapters can use it for:

- workspace-aware team routing
- team-level artifact storage
- operator dashboards that show workspace ownership

## Merge Rules

Like the agent registry and team registry, the channel registry follows:

- user config first
- project config second
- later files override earlier fields

That means:

- user-level defaults can exist in `~/.channels.json`
- project-level overrides can live in `./.channels.json`

The merge is field-wise, not whole-definition replacement.

So if the user file defines:

- `default_target_agent`
- `thread_prefix`

and the project file only changes:

- `description`

the other fields stay inherited.

## Built-In Safety Default

If no channel files exist, the system still works.

The registry automatically provides a built-in `cli` channel:

- `default_target_agent = "superagent"`
- `thread_prefix = "cli"`

That keeps the first user experience stable.

## Runtime Flow

The first real Chapter 44 flow looks like this:

```text
work console
  -> load TeamRegistry
  -> load ChannelRegistry
  -> resolve channel "cli"
  -> resolve target agent and thread key
  -> SessionRouter.resolve_or_create(...)
  -> TurnRunner.run(...)
```

And if the `cli` channel targets a team instead of an agent:

```text
cli channel
  -> default_team = support
  -> TeamRegistry.require("support")
  -> lead_agent = support-lead
  -> route turn to hosted agent "support-lead"
```

This is small, but it removes hardcoded front-door routing from the app layer.

## What `make cli` Does Now

The work console now resolves its front door from the channel system.

In code, that lives in:

- [`app.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/tui/app.py)

The `cli` route is computed through:

- channel registry
- team registry
- `resolve_cli_route(...)`

So the work console is no longer the owner of routing policy.

That responsibility now belongs to Agent OS configuration.

## New Work Console Surface

The work console now also exposes:

- `/channels`

That makes the system easier to learn and debug.

From the work side, you can now inspect:

- `/agents`
- `/channels`
- `/teams`
- `/work`
- `/goals`
- `/tasks`

This is useful because the user can see:

- which front-door route is active
- which hosted agents exist
- which teams are configured
- which work binding is attached to the current session

## Management Commands

At this point, the work console is no longer read-only for channel and team setup.

The first user-side management slice is intentionally project-scoped.

It writes to the local configuration files in the current workspace:

- `.agents.json`
- `.teams.json`
- `.channels.json`
- `.mcp.json`

The first concrete commands are:

- `/agent add <name> --workspace <path> --description "..."`
- `/team add <name> --lead <agent> [--member <name>] ...`
- `/channel add <name> (--agent <name> | --team <name>) ...`
- `/mcp add <stdio|http|sse> <name> ...`

This keeps the UX simple:

- the user can bootstrap a project locally
- the config remains visible and editable
- the runtime still discovers those files through the same registries

That gives us a good tutorial balance:

- real management commands
- still plain JSON on disk
- no hidden database or heavy admin layer yet

## Routing Commands

The work console also needs a way to change the active front door without editing config files by hand.

The first route-control command is:

- `/use <agent|team|channel> <name>`

Examples:

```text
/use agent reviewer
/use team marketing
/use channel telegram
```

This changes the current front-door route in a narrow and predictable way:

- `/use agent ...`
  switches the current session to that hosted agent on the local CLI thread
- `/use team ...`
  resolves the team lead and routes to that lead on the local CLI thread
- `/use channel ...`
  resolves both the target agent and the thread prefix from the channel definition

This is intentionally not a full routing console yet.

It is just enough to make the user-side Agent OS path real.

## Real Telegram Runtime

The earlier version of this chapter only showed a `telegram` channel as metadata.

Now we add the first real channel runtime.

The implementation lives in:

- [`telegram.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/telegram.py)
- [`mini_claw_code_py.telegram`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/telegram/__main__.py)

This runtime:

- long-polls Telegram with `getUpdates`
- maps `chat_id` into a stable Agent OS `thread_key`
- opens or reuses a gateway session
- forwards the text into the same OS gateway/runner path
- sends the reply back to Telegram with `sendMessage`

The important design rule is:

- Telegram does **not** get its own special execution engine
- it is just another channel feeding the same Agent OS backbone

So the runtime path becomes:

```text
Telegram chat
  -> TelegramChannelRuntime
  -> GatewayService
  -> MessageBus inbound
  -> TurnRunner
  -> HarnessAgent
  -> outbound reply
  -> Telegram sendMessage
```

## Running Telegram

The first runtime is started separately from the work console:

```bash
TELEGRAM_BOT_TOKEN=... make telegram
```

By default it uses:

- channel name: `telegram`

That means the recommended setup is:

1. create a `telegram` channel in `.channels.json`
2. point it to a hosted agent or team
3. start the runtime with a bot token

Example channel:

```json
{
  "channels": {
    "telegram": {
      "description": "Telegram support channel.",
      "default_team": "support",
      "thread_prefix": "tg"
    }
  }
}
```

Example team:

```json
{
  "teams": {
    "support": {
      "description": "Support and triage team.",
      "lead_agent": "support-lead",
      "member_agents": ["support-lead", "triage-bot"]
    }
  }
}
```

## Token Handling

For the first slice, we keep token handling deliberately simple:

- the bot token is supplied only when the runtime connects
- it is not stored in `.channels.json`

That keeps channel config about routing, not secrets.

Later chapters can add:

- secret managers
- per-channel credentials
- operator-managed channel connections

## Scope Limits

This first Telegram runtime is intentionally narrow.

It supports:

- text messages
- long polling
- stable session reuse per chat
- outbound text replies

It does not yet add:

- webhook hosting
- media handling
- callback buttons
- channel-specific auth policies
- operator-managed connect/disconnect flows

That is enough for the first real external channel.

## Architecture Snapshot

```text
channel definition
  -> resolves front-door target
  -> produces thread key
  -> routes into SessionRouter

team definition
  -> defines lead and members
  -> defines team workspace intent
  -> explains which domain owns the work

hosted agent definition
  -> defines the actual runnable harness agent
  -> defines that agent's workspace root
```

These three layers should stay distinct:

- channels describe entry points
- teams describe ownership and collaboration
- hosted agents describe runnable units

## What This Chapter Does Not Implement Yet

This first slice does not build:

- Telegram transport
- web dashboard transport
- cross-machine channel transport
- team-aware workspace switching in the runner
- direct member-agent task dispatch from the front door

That is intentional.

This chapter only establishes the configuration and routing layer that later channel transports will use.

## Production Insight

This separation is important for long-term growth.

Without it, the system tends to collapse into:

- one app hardcoding one front-door agent
- one global workspace
- one giant implicit routing rule

With it, we get a cleaner OS shape:

- surfaces remain thin
- routing lives in configuration and OS services
- teams gain explicit ownership
- future transports can reuse the same backend rules

## Testing Focus

The Chapter 44 tests should protect four things:

1. channel config discovery order
2. field-wise user/project merge
3. team-lead resolution from `default_team`
4. team workspace metadata parsing and rendering

Those tests live in:

- [`test_ch44.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/tests/test_ch44.py)

The work-console integration is also covered in:

- [`test_tui.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/tests/test_tui.py)

## Result

After this chapter:

- front-door routing is no longer hardcoded
- channel configuration becomes visible and testable
- teams now carry workspace intent explicitly
- `make cli` becomes a real Agent OS surface, not just a local shortcut

That is the right base before adding richer channel transports and team execution behavior later.
