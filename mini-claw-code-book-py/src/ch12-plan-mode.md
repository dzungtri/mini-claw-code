# Chapter 12: Plan Mode

Plan mode splits the workflow into two phases:

1. explore and plan with read-only tools
2. execute only after approval

The Python reference implements this in `mini_claw_code_py/planning.py`.

## PlanAgent state

`PlanAgent` stores:

- the streaming provider
- the registered tools
- a set of read-only tool names
- a plan-mode system prompt
- an `exit_plan` tool definition

## Double defense

Plan mode blocks mutation in two places:

1. it filters the tool definitions sent to the model
2. it rejects disallowed tool calls even if the model hallucinates them anyway

That second guard matters. Never trust the model to respect invisible tools by
policy alone.

## Typical flow

```text
user prompt
-> plan()
-> model explores with read/read-only bash/ask_user
-> exit_plan
-> user approval
-> execute()
-> full toolset
```

The example `mini-claw-code-py/examples/tui.py` uses exactly that pattern.
