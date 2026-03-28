# Chapter 18: Bundled Core Tools

In Chapter 17, you defined an **agent harness** as a bundled runtime with
default capabilities.

Now it is time to make that idea concrete.

The first bundled capability is the simplest one:

> the harness should not start empty

In the Chapter 17 architecture, this chapter is mainly about the
**capability plane**.

This is the part of the harness that answers:

> "What operations should a ready-to-use agent know how to perform on day one?"

A plain `SimpleAgent` starts with no tools. That is a good default for a
teaching chapter because it keeps the architecture obvious.

But a real harness should ship with a practical tool profile already attached.

## What you will build

This chapter introduces the design of `HarnessAgent`, the next runtime layer on
top of the current Python project.

Its first job is to bundle a default core tool kit.

Concretely, this chapter defines:

1. a `HarnessAgent` type that extends the current runtime shape
2. a default core tool profile
3. helper methods for bundling those tools consistently
4. the design boundary between built-in tools and later optional features
5. the path for future chapters to layer memory, summarization, sandboxing,
   and orchestration on top

That boundary matters:

- bundled core tools belong to the capability plane
- context durability and memory belong to the state plane
- workspace and sandbox belong to the environment plane
- approvals and verification belong to the control plane
- uploads, artifacts, images, and token reporting are runtime surfaces layered
  around those planes

## Why bundle core tools?

Consider these two setups.

### Manual setup every time

```python
agent = (
    PlanAgent(provider)
    .tool(ReadTool())
    .tool(WriteTool())
    .tool(EditTool())
    .tool(BashTool())
    .tool(AskTool(handler))
)
```

This is fine once.

But if every CLI entry point, every test harness, and every application setup
has to rebuild the same stack, several problems appear:

- the defaults drift
- some entry points forget a tool
- later runtime policies have no obvious home
- the "real" default agent becomes unclear

That is exactly the kind of duplication a harness should remove.

### Bundled setup

```python
agent = HarnessAgent(provider).enable_core_tools(handler)
```

Now the runtime itself defines what "the normal coding agent" should start
with.

That is much closer to how production systems are packaged.

## The design constraint

This chapter must preserve the style of `mini-claw-code-py`.

That means:

- no framework migration
- no hidden orchestration layer
- no giant configuration system
- no graph runtime
- no dependency on LangChain or LangGraph concepts

Instead, `HarnessAgent` should grow directly out of the code you already have.

The current project already gives you:

- `SimpleAgent` in `agent.py`
- `StreamingAgent` in `streaming.py`
- `PlanAgent` in `planning.py`
- `SubagentTool` in `subagent.py`
- `SkillRegistry` in `skills.py`

So the question is not:

> "What brand-new runtime should replace this?"

It is:

> "How should the harness reuse the existing runtime ideas without making the
> earlier files harder to learn?"

## Why the harness should get its own runtime file

The harness should absolutely reuse the ideas already established in
`PlanAgent`.

But that does not mean the best implementation is to keep growing
`planning.py`.

That file is still serving an important tutorial role:

- it teaches planning mode clearly
- it stays readable
- it shows the plan/execute idea without too much runtime baggage

Once the harness starts accumulating:

- bundled tools
- bundled prompts
- memory
- summarization
- workspace rules
- control-plane behavior

the code will grow quickly.

So the cleaner design for this project is:

- keep `planning.py` as the simple planning chapter runtime
- create `harness.py` as the new bundled runtime

That means `HarnessAgent` should **reuse the shape** of `PlanAgent`, but live in
its own file.

This keeps two good properties at once:

- earlier chapters stay easy to read
- later chapters get a runtime that can grow without becoming messy

## The first harness profile

A serious production harness might eventually bundle many capabilities.

But the first version in this project should stay disciplined.

Start with the tools you already have and already trust:

- `read`
- `write`
- `edit`
- `bash`
- `write_todos`
- `ask_user`

That gives the harness a practical first capability profile without collapsing
every future harness feature into the same chapter.

That gives the harness six important properties immediately:

1. it can inspect files
2. it can create files
3. it can patch files
4. it can run shell commands
5. it can keep a short visible task list
6. it can ask the user for clarification when needed

That is already a real bundled coding-agent profile.

It is also the right place to keep one architectural distinction clear:

core tools are not the entire harness.

They are only the first bundled layer.

## Why not bundle everything at once?

Because not every future harness feature is ready at the same abstraction
level.

For example:

- `subagent` belongs to orchestration, which gets its own chapter
- search tools may require new APIs or external integrations
- MCP tools belong to tool-universe management

And later harnesses may also bundle nearby capabilities such as:

- `view_image` for multimodal inspection
- artifact-presentation helpers for generated outputs
- tool-search helpers for large tool catalogs

If you force all of that into the first harness implementation, the runtime
becomes muddy.

So the better design is:

- **Chapter 18**: establish the bundled core profile
- later chapters: add more bundled capability families cleanly

That preserves clarity.

## The target API

The first harness API should feel familiar to the rest of the project.

That means a builder, not a large constructor.

The target shape looks like this:

```python
agent = HarnessAgent(provider).enable_core_tools(handler)
```

And later:

```python
agent = (
    HarnessAgent(provider)
    .enable_core_tools(handler)
    .enable_default_skills()
    .enable_memory_file(".agents/AGENTS.md")
    .workspace(".")
)
```

Notice what this preserves:

- the existing fluent style
- small methods with obvious names
- opt-in feature layering

The harness should feel like the current project evolved naturally, not like it
was replaced by a new framework.

## The class shape

The first version can stay very small.

And the cleanest home for it is:

```text
src/mini_claw_code_py/harness.py
```

The first implementation can borrow the execution shape you already trust from
`PlanAgent`, but keep its own class and its own runtime file:

```python
class HarnessAgent:
    def __init__(self, provider: StreamProvider) -> None:
        self.provider = provider
        self.tools = ToolSet()
        self._core_tools_enabled = False

    def enable_core_tools(
        self,
        handler: InputHandler | None = None,
    ) -> "HarnessAgent":
        ...
        return self
```

That `_core_tools_enabled` flag is not glamorous, but it serves a useful
purpose:

- it prevents accidental duplicate registration
- it makes the bundling method idempotent
- it keeps the API predictable

This project often prefers simple explicit state over heavier abstractions. This
fits that style well.

## What `enable_core_tools()` should do

The method should register the base tool profile in one place.

Roughly:

```python
def enable_core_tools(
    self,
    handler: InputHandler | None = None,
) -> "HarnessAgent":
    if self._core_tools_enabled:
        return self

    self.tool(ReadTool())
    self.tool(WriteTool())
    self.tool(EditTool())
    self.tool(BashTool())
    self.tool(WriteTodosTool(self._todo_board))

    if handler is not None:
        self.tool(AskTool(handler))

    self._core_tools_enabled = True
    return self
```

This design does two useful things.

### 1. It centralizes the default profile

The runtime itself now owns the definition of the default coding-agent tool
stack.

### 2. It keeps optional tools optional

`AskTool` needs an input handler, so the bundling method can add it only when
the caller provides one.

That avoids inventing a fake default handler just to satisfy the constructor.

## A small but important distinction

There are really two different categories of tools now.

### Category 1: bundled core tools

These are the default tools the harness should usually ship with.

Examples:

- `read`
- `write`
- `edit`
- `bash`
- `write_todos`
- `ask_user`

### Category 2: optional feature tools

These belong to later runtime capabilities and may require extra setup.

Examples:

- `subagent`
- search tools
- MCP-loaded tools

That distinction matters because it stops the first harness API from becoming a
grab bag.

The harness is bundled, but it should still be organized.

## The new app surface

Bundling core tools should also change how the app is started.

From this chapter onward, the tutorial should stop extending the old
`examples/chat.py` and `examples/tui.py` as the main learning path.

Those should remain as earlier simple examples.

The harness should instead get one evolving app surface:

```text
src/mini_claw_code_py/tui/work_app.py
```

The `examples/cli.py` file may still exist as a thin wrapper, but the real app
should live in the package from this point forward.

That app can start as a small copy of the current TUI shape, but from now on it
becomes the main app the later chapters continue extending.

That gives the project one stable growth path:

- old example apps stay simple
- new harness CLI keeps evolving

## The prompt implication

Bundling tools changes more than registration.

It also changes the default prompt story.

Once `HarnessAgent` ships with a known core profile, the system prompt can
start to assume those tools are normal parts of the environment.

For example, the harness prompt can safely teach norms such as:

- read before edit
- inspect before changing code
- use shell commands for verification
- ask the user when required information is missing

That is not a new mechanism. The project already has prompt composition in
`render_system_prompt()`.

The harness simply gives those prompt rules a more stable runtime target.

## Why this belongs in the harness, not in every app

You could push all of this into the example CLI.

But that would be the wrong abstraction level.

The CLI is just one consumer of the runtime.

The default core tool profile is a property of the **runtime itself**.

So the ownership should be:

- `HarnessAgent` defines the bundled default
- the CLI uses that bundled default
- tests can opt in to the bundled default
- future apps can opt in to the same bundled default

That is exactly the kind of reuse a harness should provide.

## Compatibility with earlier chapters

Introducing `HarnessAgent` should not invalidate the earlier agent types.

They still have clear roles:

- `SimpleAgent` teaches the core loop
- `StreamingAgent` teaches streamed execution
- `PlanAgent` teaches planning and controlled execution
- `HarnessAgent` packages the mature default runtime profile

That progression is healthy.

It mirrors how real systems evolve:

1. start with a tiny loop
2. add tools
3. add planning
4. add delegation
5. finally package the stable defaults as a harness

So the harness is not "the only correct agent".

It is the most complete runtime profile built on top of the earlier ones.

## One possible file layout

The cleanest home for the first implementation is:

```text
mini_claw_code_py/
├── agent.py
├── streaming.py
├── planning.py
├── harness.py
└── tools/
```

Why a new `harness.py` file?

Because the harness is now a distinct runtime concept.

It should not be hidden inside `planning.py`, even if it inherits from
`PlanAgent`.

That keeps the mental model clean:

- `planning.py` explains planning behavior
- `harness.py` explains the bundled runtime profile

## A realistic first milestone

The first implementation milestone for `HarnessAgent` does **not** need to
solve every future harness concern.

It only needs to prove one thing:

> the runtime can own a bundled default tool profile

If that part is clean, later chapters can extend it with:

- memory
- summarization
- workspace rules
- subagent orchestration
- tool-universe management
- control-plane features

That is the right order.

## Recap

The first concrete step from agent to harness is bundling a default core tool
profile.

In this project, the cleanest design is:

- introduce `HarnessAgent`
- inherit from `PlanAgent`
- keep the existing builder style
- centralize the default tool kit in `enable_core_tools()`
- separate bundled core tools from later optional feature tools

This keeps the codebase consistent with everything you already built while
moving it toward a more realistic runtime shape.

## What's next

In [Chapter 19: Context Durability](./ch19-context-durability.md) you will add
the next major harness feature: surviving long tasks by compacting stale
history without losing task continuity.
