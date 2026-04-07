# Chapter 8: The Singularity

This is the short pause after the first full build.

At this point you already have the important pieces:

- typed messages and tool calls
- a tool registry
- a provider that can talk to OpenAI or Gemini
- a single-turn helper
- a looping agent
- a working CLI

The rest of the book adds runtime polish and safety boundaries. That is where
agent software stops being a demo and starts becoming useful in real projects.

## What To Remember

The model is not the program. The program is the loop around the model. That
loop gives you control, safety, observability, and testability.

## What Comes Next

The next chapters add:

- streaming output
- better terminal UX
- user input tools
- plan mode
- subagents
- external tool integration
- safety rails

## Why This Pause Matters

The architecture is already complete in the first half of the book. From here
on, you are not changing the core idea. You are extending it:

- streaming makes the agent feel alive
- the TUI makes the interaction easier to read
- user input lets the model ask for clarification
- plan mode separates exploration from execution
- subagents make complex work easier to split up

That is the shape of real agent software: a small, stable core with focused
extensions around it.

