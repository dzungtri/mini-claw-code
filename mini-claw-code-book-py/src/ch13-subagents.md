# Chapter 13: Subagents

Subagents help when one conversation is trying to do too much at once.

The Python port treats a subagent as just another tool:

```python
SubagentTool(provider, lambda: ToolSet().with_tool(ReadTool()))
```

## Design

`SubagentTool` stores:

- the shared provider
- a `tools_factory` callback that creates a fresh child `ToolSet`
- an optional child system prompt
- a maximum turn limit

## Why a factory?

Each child needs clean tool state. A callback is simpler than trying to clone a
heterogeneous tool collection.

## Child loop

Inside `call()` the subagent:

1. builds a fresh child history
2. runs the same provider/tool loop as `SimpleAgent`
3. returns only the child's final text to the parent

The parent does not see the child's internal messages. It only sees one tool
result summary.

That keeps parent context smaller and makes decomposition practical.
