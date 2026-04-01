# Chapter 15: Safety Rails

The agent you've built in this book is powerful. It can read files, write files,
edit code, run shell commands, ask the user questions, and delegate work to
subagents. That power is the point -- but it is also the risk.

An unrestricted coding agent can:

- overwrite the wrong file
- run a destructive shell command
- leak secrets through an overly broad tool call
- mutate the workspace before the user has reviewed the plan

That is why real agents need **safety rails**.

The important lesson is that safety is not one big switch. In the Rust Claw
Code reference implementation, it is spread across several layers:

- `crates/runtime/src/permissions.rs`
- `crates/runtime/src/conversation.rs`
- `crates/runtime/src/sandbox.rs`
- `crates/runtime/src/bash.rs`
- `crates/tools/src/lib.rs`

That layering is the design to copy.

In this chapter you'll design a safety system for `mini-claw-code` inspired by
those modules.

You will:

1. Assign each tool a required permission level.
2. Define a `PermissionPolicy` that decides whether a tool call may run.
3. Add an approval prompt for dangerous escalations.
4. Enforce permissions *inside* the agent loop, not only in the UI.
5. Add sandboxing as a second line of defense for shell commands.
6. Keep the whole system additive: the agent loop stays recognizable.

## Why safety rails?

Imagine this prompt:

```text
User: "Clean up the workspace and fix whatever looks broken"
```

Without guardrails, the model could decide to:

- run `rm -rf tmp/`
- rewrite config files
- mutate unrelated code
- execute a broad shell pipeline it barely understands

Even if the model is trying to help, that is too much authority.

The fix is not "trust the model less." The fix is to structure the runtime so
that **dangerous actions pass through explicit gates**.

A good safety architecture answers three separate questions:

1. **Should this tool be allowed at all?**
2. **If allowed, should it require approval first?**
3. **If it runs, can the runtime still confine the blast radius?**

Permissions answer the first two. Sandboxing answers the third.

## Permission modes

The reference implementation uses an ordered enum:

```rust
pub enum PermissionMode {
    ReadOnly,
    WorkspaceWrite,
    DangerFullAccess,
    Prompt,
    Allow,
}
```

The names tell the story:

- **`ReadOnly`**: safe inspection only
- **`WorkspaceWrite`**: may modify files in the workspace
- **`DangerFullAccess`**: may run tools with broader machine impact
- **`Prompt`**: require explicit approval before running tools
- **`Allow`**: bypass checks entirely

For a tutorial agent, the most important three are still `ReadOnly`,
`WorkspaceWrite`, and `DangerFullAccess`. Those map cleanly onto the tools
you already know from earlier chapters.

The subtle part is ordering. Because the enum derives ordering traits, the
policy can ask a simple question:

```rust
current_mode >= required_mode ?
```

If yes, allow it. If not, decide whether to deny outright or prompt.

## Every tool declares what it needs

Permissions work best when the rule lives next to the tool definition.

The reference `crates/tools/src/lib.rs` does this with `ToolSpec`:

```rust
pub struct ToolSpec {
    pub name: &'static str,
    pub description: &'static str,
    pub input_schema: Value,
    pub required_permission: PermissionMode,
}
```

That is the right boundary.

A tool should not be able to quietly become more dangerous without its spec
changing too.

A minimal mapping looks like this:

```rust
read_file   -> ReadOnly
write_file  -> WorkspaceWrite
edit_file   -> WorkspaceWrite
bash        -> DangerFullAccess
```

This is better than hard-coding special cases in the agent loop because the
policy can be built mechanically from the tool registry.

## The permission policy

`PermissionPolicy` owns two pieces of state:

- the **active mode** right now
- the **required mode** for each tool

The core API in the reference runtime is:

```rust
pub fn authorize(
    &self,
    tool_name: &str,
    input: &str,
    prompter: Option<&mut dyn PermissionPrompter>,
) -> PermissionOutcome
```

That function returns either:

- `PermissionOutcome::Allow`
- `PermissionOutcome::Deny { reason }`

This is a strong design. It keeps permission checks declarative.

The agent loop does not need to know *why* a tool was blocked. It only needs a
clear yes/no answer and an explanation string that can be returned to the LLM.

## Approval is a policy decision, not a UI feature

A common mistake is to put approval logic only in the terminal UI.

That is too weak.

If the runtime itself does not enforce approvals, a different front-end -- a
TUI, a web app, or a test harness -- could accidentally bypass the check.

The reference implementation avoids that by introducing a
`PermissionPrompter` trait:

```rust
pub trait PermissionPrompter {
    fn decide(&mut self, request: &PermissionRequest) -> PermissionPromptDecision;
}
```

Now the runtime can ask for approval *without* knowing how the question is
rendered.

The policy decides when to prompt. The UI only decides how to display the
prompt.

That is exactly the same separation you used in Chapter 11 for user input:

- policy/runtime layer decides **when** input is needed
- front-end layer decides **how** to collect it

## Workspace-write to danger-full-access is the critical escalation

The reference policy has a particularly useful rule:

- if the current mode is `WorkspaceWrite`
- and the requested tool needs `DangerFullAccess`
- prompt before escalating

That matches how real coding agents feel in practice.

Editing files in the repository is one class of risk. Running arbitrary shell
commands is a bigger one.

So a flow like this makes sense:

```text
mode = WorkspaceWrite
LLM calls write_file   -> allowed
LLM calls edit_file    -> allowed
LLM calls bash         -> prompt user first
```

This gives the user a practical middle ground: let the agent refactor code, but
do not let it run unrestricted shell commands silently.

## Put the guard inside the agent loop

The most important integration point is in the runtime loop itself.

The reference `ConversationRuntime::run_turn()` does the check *after* the LLM
has requested a tool, but *before* the tool executes:

```rust
let permission_outcome = self.permission_policy.authorize(&tool_name, &input, ...);

match permission_outcome {
    PermissionOutcome::Allow => {
        // execute tool
    }
    PermissionOutcome::Deny { reason } => {
        // send tool_result error back to the model
    }
}
```

This is exactly where the check belongs.

Why?

Because the runtime is the last trustworthy boundary before side effects happen.
Once `tool_executor.execute(...)` runs, it is too late.

There is another nice property here: denied tool calls become ordinary
`tool_result` messages in the conversation history. The LLM sees the refusal and
can adapt.

That is much better than crashing the entire turn.

## Safety is defense in depth

Permissions alone are not enough.

Suppose the user approves a `bash` command. You still might want the command to:

- run with a restricted filesystem view
- lose network access
- use a temporary HOME directory
- run with a timeout

That is the job of sandboxing.

The reference `sandbox.rs` splits this into two concepts:

1. a **requested configuration** (`SandboxRequest`)
2. a **resolved runtime status** (`SandboxStatus`)

That distinction matters because the runtime may not be able to honor every
request on every platform.

For example:

- Linux with `unshare` available can enable namespace isolation
- macOS may fall back to a weaker mode
- allow-list filesystem mode is invalid if no mounts are configured

Instead of pretending everything worked, the runtime records what actually
happened.

That is honest engineering.

## Sandboxing the bash tool

The shell tool is where safety becomes concrete.

In `runtime/src/bash.rs`, the command input can request sandbox-related options:

```rust
pub struct BashCommandInput {
    pub command: String,
    pub timeout: Option<u64>,
    pub dangerously_disable_sandbox: Option<bool>,
    pub namespace_restrictions: Option<bool>,
    pub isolate_network: Option<bool>,
    pub filesystem_mode: Option<FilesystemIsolationMode>,
    pub allowed_mounts: Option<Vec<String>>,
}
```

That is a great example of additive design.

The basic bash tool still does one thing: run a command. Safety features are
layered around it.

The flow is:

1. Load sandbox defaults from config
2. Merge in per-call overrides
3. Resolve the actual `SandboxStatus`
4. Build the command launcher
5. If possible, wrap the command in Linux `unshare`
6. If filesystem isolation is active, rewrite `HOME` and `TMPDIR`

The output even includes the resolved sandbox status, so callers can see what
protections were active during execution.

## Timeouts are safety features too

It is easy to think of timeouts as a convenience feature. They are also a safety
rail.

A shell command that hangs forever is not harmless just because it never wrote a
file. It still blocks progress, may hold resources open, and may leave the user
with no idea what happened.

The reference bash tool treats timeout as part of the contract:

- the input may request one
- the runtime interrupts long-running commands
- the output marks the command as interrupted

That is exactly right. Resource control is part of safety.

## Hooks and policy can compose

The reference runtime also has pre/post tool hooks in `conversation.rs`.
Those are not the primary safety boundary, but they fit naturally on top of the
permission system.

A useful mental model is:

- **Permissions** decide whether the tool may run
- **Hooks** add organization-specific checks or logging
- **Sandboxing** constrains execution if the tool does run

That stack is stronger than any one mechanism alone.

## Practical defaults for a mini agent

If you add safety rails to `mini-claw-code`, start simple:

1. `read` is read-only
2. `write` and `edit` require workspace-write
3. `bash` requires danger-full-access
4. denied tool calls become error `ToolResult`s
5. shell commands support timeouts
6. shell commands run with the strongest sandbox the platform can support

That already gives you a meaningful security story without turning the book into
a sandboxing textbook.

## Running the safety review

Before you call a safety system "done," make sure it answers these questions:

- Can every tool declare its required permission level?
- Is the permission check inside the runtime loop?
- Can dangerous escalations request approval?
- Do denied calls return structured feedback to the model?
- Does `bash` expose timeout and sandbox controls?
- Can the runtime report which sandbox protections were actually active?

If the answer to any of those is no, your safety story is probably incomplete.

## Recap

- **Safety rails are layered** -- permissions, approval, sandboxing, and
  timeouts solve different problems.
- **Tool specs should declare required permission levels** so policy stays close
  to capability.
- **`PermissionPolicy`** turns tool requests into `Allow` or `Deny { reason }`.
- **Approval belongs in the runtime contract**, not just in the UI.
- **The agent loop is the enforcement point**: check permission before tool
  execution, then return either output or a denial result.
- **Sandboxing is defense in depth** for commands that are allowed to run.
- **Purely additive**: you can add real safety rails without throwing away the
  agent architecture you've built in the earlier chapters.
