# Overview

Welcome to *Build Your Own Mini Coding Agent in TypeScript*. Over the next
seven chapters you will implement a mini coding agent from scratch -- a small
version of programs like Claude Code or OpenCode -- a program that takes a
prompt, talks to a large-language model (LLM), and uses *tools* to interact
with the real world. After that, a series of extension chapters add
streaming, a TUI, user input, plan mode, subagents, and more.

By the end of this book you will have an agent that can run shell commands,
read and write files, edit code, and ask follow-up questions, all driven by an
LLM. No API key is required until Chapter 6. When you get there, the provider
layer is designed so students can use either OpenAI directly or Gemini through
an OpenAI-compatible endpoint.

## What is an AI agent?

An LLM on its own is a function: text in, text out. Ask it to summarize
`doc.pdf` and it will either refuse or hallucinate -- it has no way to open the
file.

An **agent** solves this by giving the LLM **tools**. A tool is just a function
your code can run -- read a file, execute a shell command, call an API, prompt
the user. The agent sits in a loop:

1. Send the user's prompt to the LLM.
2. The LLM decides it needs a tool and outputs a tool call.
3. Your code executes that tool and feeds the result back.
4. The LLM sees the new information and either answers or asks for another tool.

The LLM never touches the filesystem directly. It just *asks*, and your code
*does*. That loop -- ask, execute, feed back -- is the entire idea.

## LLM model vs agent vs harnessed agent

It helps to separate three layers that people often collapse into one:

### 1. LLM model

A raw LLM model is the reasoning engine. It predicts the next tokens. That is
useful, but limited:

- it cannot inspect your repo directly
- it cannot execute commands
- it cannot keep trustworthy workflow state by itself
- it cannot enforce human review or operational boundaries

If you build only a thin LLM wrapper, you usually get a chat interface that can
answer questions, but not a system that can reliably complete engineering work.

### 2. Agent

An **agent** is an LLM plus tools plus a loop. The loop lets the model inspect
state, act, observe results, and continue. This is the first major step up in
capability:

- read files
- run shell commands
- write or edit code
- ask follow-up questions

That is why this book is about building an agent, not just building a cleaner
wrapper around a model API.

### 3. Harnessed agent

A **harnessed agent** wraps the agent loop inside a controlled execution
environment. The harness is what makes the agent dependable enough to use in a
real workflow instead of as a demo.

A harness can add:

- controlled tool registration
- working-directory awareness
- streaming output and event handling
- user-input gates
- plan / execute separation
- mock providers and test hooks
- limits, logging, and safety rails

In other words, the harness is the part that turns "the model can call tools"
into "the system can complete tasks in a way humans can observe, review, and
trust."

## Why not stop at an LLM wrapper?

A plain LLM wrapper is enough for:

- chat
- summarization
- answering questions from provided context

But software work needs more than that. Real coding tasks require a system
that can:

1. inspect files and directories
2. choose the next action based on what it found
3. execute actions in sequence
4. recover from tool failures
5. keep the human in the loop when needed

That is what the agent loop and the harness around it provide.

You can think of the progression like this:

```text
LLM model        = thinks
Agent            = thinks + acts
Harnessed agent  = thinks + acts + operates safely inside a workflow
```

This book starts with the smallest useful unit: the agent core. Later chapters
add the harness pieces that make the system stronger: streaming, user input,
plan mode, subagents, and safety.

## How does an LLM use a tool?

An LLM cannot execute code. It is a text generator. So "calling a tool" really
means the LLM *outputs a structured request* and your code does the rest.

When you send a request to the LLM, you include a list of **tool definitions**
alongside the conversation. Each definition has:

- a name
- a description
- a JSON Schema object describing its arguments

The model can then answer in two ways:

1. It can stop and return plain text.
2. It can stop and return one or more tool calls.

Your runtime inspects that response, executes the tool calls, and appends the
results to the conversation history.

This is why agent code is so small. The model does the reasoning. Your program
just implements the protocol and the tools.

## Why TypeScript?

The Rust version of this tutorial uses traits, enums, and async runtimes to
teach the same architecture. In this edition we keep the ideas but express them
with Bun and TypeScript:

- **Discriminated unions** represent conversation messages and events.
- **`Promise` + `async` / `await`** replace trait-returned futures.
- **`Map<string, Tool>`** gives O(1) tool lookup.
- **Global `fetch()`** and Bun's runtime APIs keep the provider small.
- **Bun's test runner** makes each chapter easy to verify.

The TypeScript version is not a "toy port." It teaches the same agent design,
just in a form that is more familiar to students already writing web and app
code in JavaScript and TypeScript.

## What you will build

The first seven chapters are hands-on:

- **Chapter 1** introduces the protocol types and a mock provider.
- **Chapter 2** builds your first tool: `read`.
- **Chapter 3** implements a single-turn tool call flow.
- **Chapter 4** adds more tools: `bash`, `write`, and `edit`.
- **Chapter 5** builds the agent loop.
- **Chapter 6** adds a real HTTP provider.
- **Chapter 7** turns it into a CLI chat program.

After that, the extension chapters cover:

- a better terminal UI
- streaming
- user input
- plan mode
- subagents
- safety and future directions

## The project layout

This repository now contains both the original Rust track and the TypeScript
track. The TypeScript side is split into three packages:

```text
mini-claw-code-book-ts/          # this tutorial
mini-claw-code-starter-ts/       # starter code students fill in
mini-claw-code-ts/               # completed reference implementation
```

The pattern mirrors the Rust version:

- the **starter** package is incomplete on purpose
- the **solution** package is the reference implementation
- the **book** explains the concepts and points students at the right files

You will spend most of your time in `mini-claw-code-starter-ts/` while using
`mini-claw-code-ts/` as the finished target architecture.

## The key design choice

This tutorial is intentionally minimal. It does not start with a framework,
state machine library, React app, or database. It starts with the smallest
thing that can possibly work:

- a provider interface
- a tool interface
- a message history
- an agent loop

That small core is enough to teach the architecture clearly. Once you
understand it, everything else in production-grade agents feels like an
extension instead of magic.

## What you should know first

You do not need to be an expert in AI or distributed systems. You do need a
few basics:

- TypeScript syntax
- `async` / `await`
- Node/Bun file and process APIs at a high level
- JSON and HTTP fundamentals

If you are comfortable reading TypeScript classes, interfaces, unions, and
Promises, you are ready.

## How to use this book

For Chapters 1-7:

1. Read the chapter.
2. Open the matching file in `mini-claw-code-starter-ts/`.
3. Implement the missing code.
4. Run the chapter test.

The later chapters are meant as reference and extension material. You can
either continue implementing them yourself or read the finished code in
`mini-claw-code-ts/`.

## The end goal

By the time you finish Chapter 7, you will already have built a real agent.
It will be small, but it will not be fake:

- it will call a real model provider
- it will execute real tools
- it will maintain conversation history
- it will recover from tool errors

That is enough to understand how agent software actually works.
