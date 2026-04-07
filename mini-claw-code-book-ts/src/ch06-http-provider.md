# Chapter 6: The OpenAI-Compatible Provider

Up to now, everything has run locally with `MockProvider`. In this chapter you
will implement `OpenAICompatibleProvider` - the provider that talks to a real
model backend over HTTP using the OpenAI-compatible chat completions API.

This is the chapter that makes your agent real.

## Goal

Implement `OpenAICompatibleProvider` in `mini-claw-code-starter-ts` so that:

1. It can be created with an API key and model name.
2. It converts our internal `Message` and `ToolDefinition` values to the API
   format.
3. It sends HTTP `POST` requests to the chat completions endpoint.
4. It parses responses back into `AssistantTurn`.

## Why one provider?

The TypeScript track uses a single provider abstraction because both OpenAI
and Gemini can be reached through the same OpenAI-compatible shape. That keeps
the agent code simple:

- `baseUrl` points at OpenAI or Gemini.
- `apiKey` comes from the matching environment variable.
- `model` comes from configuration or the environment.

The rest of the agent does not care which vendor is behind the interface.

## Why `fetch()`?

Bun gives you global `fetch`, so the provider does not need an extra HTTP
library. That keeps the dependency surface tiny and makes the request flow easy
to read:

```ts
const response = await fetch(`${this.baseUrl}/chat/completions`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${this.apiKey}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify(payload),
});
```

The flow mirrors the Rust version closely: build a payload, send it, check the
status, parse the JSON, and convert the response back into your internal type.

## The API shapes

Open `mini-claw-code-starter-ts/src/providers/openai-compatible.ts`. The file
already contains the helper types for the wire format:

```ts
type ChatRequest = {
  model: string;
  messages: ApiMessage[];
  tools: ApiTool[];
};

type ApiMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content?: string;
  tool_calls?: ApiToolCall[];
  tool_call_id?: string;
};

type ApiToolCall = {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
};

type ApiTool = {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: unknown;
  };
};
```

These helpers are only for the wire protocol. The rest of the code keeps using
the cleaner discriminated-union model from Chapter 1.

The shape matches the OpenAI-compatible chat completions API:

- `messages` is the conversation history
- `tools` describes the tools the model can call
- `tool_calls` comes back when the model wants a tool result
- `finish_reason` tells you whether the model stopped or requested tools

## TypeScript concepts

### Exact object shapes

TypeScript lets you encode the API shape directly. That is useful here because
the JSON payload has a few fields that should only appear when they are needed.

When a field is unused, prefer omitting it rather than forcing it to `undefined`
or `null` in the request object. That keeps the wire format aligned with the API
and makes the conversion code easier to reason about.

### JSON conversion

The provider has to bridge two worlds:

- Your internal `Message`, `ToolDefinition`, and `AssistantTurn` types
- The JSON request and response format used by the model API

In TypeScript, that conversion is explicit and mechanical. You will use
`JSON.stringify()` when sending tool arguments and `JSON.parse()` when reading
them back.

### Environment variables

The TypeScript starter uses `process.env` directly. Bun loads `.env` files for
you, so a student can place an API key in the workspace root and run the
chapter example without extra setup.

## What the provider should do

The starter file already gives you the method signatures. Your job is to make
them work:

```ts
export class OpenAICompatibleProvider implements Provider {
  static new(apiKey: string, model: string, baseUrl?: string): OpenAICompatibleProvider
  withBaseUrl(url: string): OpenAICompatibleProvider
  static fromEnv(model = "gpt-4.1-mini"): OpenAICompatibleProvider
  static convertMessages(messages: Message[]): ApiMessage[]
  static convertTools(tools: ToolDefinition[]): ApiTool[]
  async chat(messages: Message[], tools: ToolDefinition[]): Promise<AssistantTurn>
}
```

That shape maps almost one-to-one with the Rust chapter:

1. constructor
2. base URL builder
3. environment-based constructor
4. message conversion
5. tool conversion
6. the request/response round trip

## Step 1: `new()`

Initialize the three fields:

```ts
constructor(
  readonly apiKey: string,
  readonly model: string,
  readonly baseUrl = "https://api.openai.com/v1",
) {}
```

The default base URL points to OpenAI. `withBaseUrl()` can later switch it to a
Gemini-compatible endpoint.

## Step 2: `withBaseUrl()`

This should return a cloned provider with the same API key and model but a new
endpoint:

```ts
withBaseUrl(url: string): OpenAICompatibleProvider {
  return new OpenAICompatibleProvider(this.apiKey, this.model, url);
}
```

That tiny builder method matters because it keeps the constructor simple while
still letting the book talk about multiple vendors.

## Step 3: `fromEnv()`

The starter version keeps the environment logic compact. A practical
implementation can:

1. Read the API key from `OPENAI_API_KEY` or `GEMINI_API_KEY`.
2. Use the default model unless the environment overrides it.
3. Use `withBaseUrl()` if the key came from Gemini.

The key lesson is not the exact variable names. It is that the provider should
remain configurable without changing the rest of the agent.

## Step 4: `convertMessages()`

This method translates your internal `Message` union into the API message
format. The logic is small but important:

- `system` becomes `{ role: "system", content: text }`
- `user` becomes `{ role: "user", content: text }`
- `assistant` becomes `{ role: "assistant", content, tool_calls? }`
- `tool_result` becomes `{ role: "tool", content, tool_call_id }`

The assistant branch is the only tricky one because tool calls need to be
serialized:

```ts
{
  id: call.id,
  type: "function",
  function: {
    name: call.name,
    arguments: JSON.stringify(call.arguments),
  },
}
```

If `toolCalls` is empty, leave it out of the object entirely.

## Step 5: `convertTools()`

Map each `ToolDefinition` into the API tool format:

```ts
{
  type: "function",
  function: {
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
  },
}
```

This is the same idea as the Rust version: the model needs enough schema
information to know what arguments it can supply.

## Step 6: `chat()`

This is the main method. It ties together the whole provider:

1. Build a `ChatRequest`.
2. Send it to `${baseUrl}/chat/completions`.
3. Check for HTTP errors.
4. Parse the response as JSON.
5. Convert the first choice into `AssistantTurn`.

The tool-call conversion is the most important part. The API returns tool
arguments as a string, so you need to parse them back into a JSON value:

```ts
const toolCalls = (choice.message.tool_calls ?? []).map((call) => ({
  id: call.id,
  name: call.function.name,
  arguments: JSON.parse(call.function.arguments),
}));
```

Then map `finish_reason` to your internal `stopReason`:

- `"tool_calls"` becomes `"tool_use"`
- anything else becomes `"stop"`

## Implementation Notes

The book should keep the provider logic small and explicit:

- build request objects with plain JavaScript objects
- use `JSON.stringify()` at the boundary
- use `await response.json()` when reading the result
- keep the model-specific details in configuration, not in the agent loop

That keeps the provider easy to test and easy to extend.

## Tests

Run the Chapter 6 tests:

```bash
bun test mini-claw-code-starter-ts/tests/ch6.test.ts
```

The tests verify:

- tool definition conversion
- message conversion
- environment-based construction
- the full `chat()` request/response path

Those tests use a local mock server, so no real API key is required.

## Recap

You have built a real HTTP provider that:

- constructs from an API key and model name
- converts between internal types and OpenAI-compatible JSON
- sends HTTP requests and parses responses
- works with OpenAI and Gemini through the same abstraction

The important patterns are:

- `fetch()` for the HTTP layer
- explicit JSON conversion at the boundary
- a small provider interface that keeps the rest of the agent clean

Next you will wire the provider into a CLI chat loop.
