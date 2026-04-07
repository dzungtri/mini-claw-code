# Chapter 9: A Better TUI

The chat CLI from Chapter 7 works, but it is still plain text. A real coding
agent needs better terminal behavior: a spinner while the model is thinking,
concise tool call summaries, support for streamed text, and a place to pause
for user input.

This chapter explains the shape of that terminal UI and how it sits on top of
the agent runtime.

## What The TUI Needs

At a minimum, the interface should do four things well:

1. Show that the agent is working.
2. Render assistant text as it arrives.
3. Show tool usage without flooding the screen.
4. Pause cleanly when the agent needs the user to answer a question.

That is enough to make a coding assistant feel responsive instead of blocking.

## Event-Driven UI

The TypeScript track keeps the UI separate from the agent by using events.
The agent emits events; the TUI decides how to render them.

The solution package models those events as a discriminated union:

```ts
export type AgentEvent =
  | { kind: "text_delta"; text: string }
  | { kind: "tool_call"; name: string; summary: string }
  | { kind: "done"; text: string }
  | { kind: "error"; error: string };
```

That shape is deliberate:

- `text_delta` lets the UI print partial assistant output immediately.
- `tool_call` gives the UI a one-line summary for each tool invocation.
- `done` tells the UI to stop the spinner and render the final response.
- `error` keeps the terminal loop alive when the model or a tool fails.

This keeps rendering concerns out of the agent loop. The agent orchestrates;
the TUI paints.

## A Better Terminal Loop

The user-facing loop is still simple:

1. Read a prompt.
2. Push it into the conversation history.
3. Start the agent request.
4. Render progress while the request is running.
5. Print the final answer when the request finishes.

The difference from a plain CLI is that the TUI needs to manage more state:

- a spinner frame counter
- a buffered text area for streamed output
- a count of tool calls so it can collapse the noisy ones
- a separate input path when `AskTool` pauses the run

In TypeScript, that state usually lives in one module and is driven by
callbacks or async events.

## Rendering Strategy

The Rust version uses `termimad`, `crossterm`, and a custom event loop to keep
the screen tidy. The TypeScript version can follow the same idea even if the
terminal libraries differ:

- render streamed assistant text incrementally
- collapse repeated tool calls after the first few
- clear the spinner line before printing final markdown
- redraw the spinner when the next chunk arrives

The exact library choice is less important than the boundary between agent
events and rendering logic.

## User Input Pauses

When the model asks a question, the UI must stop acting like a fire-and-forget
prompt and become a conversation surface.

That is why the input tool is split from the agent:

- `AskTool` produces a `UserInputRequest`
- the TUI owns the actual prompt or selection widget
- the answer is sent back through the handler and the agent continues

The rendering loop should pause while input is active, then resume as soon as
the answer is available.

## Where This Fits In The Architecture

By this point the architecture has three layers:

```text
Provider  ->  Agent  ->  UI
```

The provider speaks to the model.
The agent handles the loop and tool execution.
The UI handles the terminal experience.

Keeping those layers separate is what makes the later chapters possible.

## Recap

- A TUI is mostly an event renderer sitting on top of the agent loop.
- Streaming text, tool summaries, and user prompts each need different UI
  handling.
- The UI should stay out of the agent protocol itself.
- Once the event boundary is clean, you can improve the terminal experience
  without changing the model orchestration code.

The next chapter shows the streaming boundary that makes this UI feel alive.

