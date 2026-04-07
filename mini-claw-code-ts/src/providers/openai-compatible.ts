import {
  StreamAccumulator,
  parseSseLine,
  type StreamEventHandler,
  type StreamProvider,
} from "../streaming";
import type {
  AssistantTurn,
  JsonValue,
  Message,
  Provider,
  ToolCall,
  ToolDefinition,
} from "../types";

interface ApiMessage {
  role: "system" | "user" | "assistant" | "tool";
  content?: string | null | undefined;
  tool_calls?: ApiToolCall[] | undefined;
  tool_call_id?: string | undefined;
}

interface ApiToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
}

interface ChatRequestBody {
  model: string;
  messages: ApiMessage[];
  tools: Array<{
    type: "function";
    function: {
      name: string;
      description: string;
      parameters: JsonValue;
    };
  }>;
  stream?: boolean;
}

interface ChatResponseBody {
  choices: Array<{
    message: {
      content?: string | null;
      tool_calls?: ApiToolCall[] | null;
    };
    finish_reason?: string | null;
  }>;
}

export class OpenAICompatibleProvider implements Provider, StreamProvider {
  static readonly OPENAI_BASE_URL = "https://api.openai.com/v1";
  static readonly GEMINI_OPENAI_BASE_URL =
    "https://generativelanguage.googleapis.com/v1beta/openai";
  static readonly DEFAULT_OPENAI_MODEL = "gpt-5-mini";
  static readonly DEFAULT_GEMINI_MODEL = "gemini-2.5-flash";

  readonly #apiKey: string;
  readonly #model: string;
  readonly #baseUrl: string;

  constructor(apiKey: string, model: string, baseUrl = OpenAICompatibleProvider.OPENAI_BASE_URL) {
    this.#apiKey = apiKey;
    this.#model = model;
    this.#baseUrl = baseUrl;
  }

  static fromOpenAIEnv(): OpenAICompatibleProvider {
    const apiKey = readRequiredEnv("OPENAI_API_KEY");
    const model = process.env.OPENAI_MODEL?.trim() || OpenAICompatibleProvider.DEFAULT_OPENAI_MODEL;
    return new OpenAICompatibleProvider(apiKey, model, OpenAICompatibleProvider.OPENAI_BASE_URL);
  }

  static fromGeminiEnv(): OpenAICompatibleProvider {
    const apiKey = readRequiredEnv("GEMINI_API_KEY");
    const model =
      process.env.GEMINI_MODEL?.trim() || OpenAICompatibleProvider.DEFAULT_GEMINI_MODEL;
    return new OpenAICompatibleProvider(
      apiKey,
      model,
      process.env.GEMINI_BASE_URL?.trim() || OpenAICompatibleProvider.GEMINI_OPENAI_BASE_URL,
    );
  }

  static fromEnv(): OpenAICompatibleProvider {
    if (process.env.OPENAI_API_KEY?.trim()) {
      return OpenAICompatibleProvider.fromOpenAIEnv();
    }
    if (process.env.GEMINI_API_KEY?.trim()) {
      return OpenAICompatibleProvider.fromGeminiEnv();
    }
    throw new Error("No API key found. Set OPENAI_API_KEY or GEMINI_API_KEY.");
  }

  static fromEnvWithModel(model: string): OpenAICompatibleProvider {
    if (process.env.OPENAI_API_KEY?.trim()) {
      return new OpenAICompatibleProvider(
        readRequiredEnv("OPENAI_API_KEY"),
        model,
        process.env.OPENAI_BASE_URL?.trim() || OpenAICompatibleProvider.OPENAI_BASE_URL,
      );
    }
    if (process.env.GEMINI_API_KEY?.trim()) {
      return new OpenAICompatibleProvider(
        readRequiredEnv("GEMINI_API_KEY"),
        model,
        process.env.GEMINI_BASE_URL?.trim() || OpenAICompatibleProvider.GEMINI_OPENAI_BASE_URL,
      );
    }
    throw new Error("No API key found. Set OPENAI_API_KEY or GEMINI_API_KEY.");
  }

  withBaseUrl(url: string): OpenAICompatibleProvider {
    return new OpenAICompatibleProvider(this.#apiKey, this.#model, url);
  }

  baseUrl(url: string): OpenAICompatibleProvider {
    return this.withBaseUrl(url);
  }

  static convertMessages(messages: Message[]): ApiMessage[] {
    return messages.map((message) => {
      switch (message.kind) {
        case "system":
          return { role: "system", content: message.text };
        case "user":
          return { role: "user", content: message.text };
        case "assistant":
          return {
            role: "assistant",
            content: message.turn.text ?? null,
            ...(message.turn.toolCalls.length > 0
              ? {
                  tool_calls: message.turn.toolCalls.map((call) => ({
                    id: call.id,
                    type: "function" as const,
                    function: {
                      name: call.name,
                      arguments: JSON.stringify(call.arguments),
                    },
                  })),
                }
              : {}),
          };
        case "tool_result":
          return {
            role: "tool",
            content: message.content,
            tool_call_id: message.id,
          };
      }
    });
  }

  static convertTools(tools: ToolDefinition[]): ChatRequestBody["tools"] {
    return tools.map((tool) => ({
      type: "function",
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
      },
    }));
  }

  async chat(messages: Message[], tools: ToolDefinition[]): Promise<AssistantTurn> {
    const response = await fetch(`${this.#baseUrl}/chat/completions`, {
      method: "POST",
      headers: this.#headers(),
      body: JSON.stringify({
        model: this.#model,
        messages: OpenAICompatibleProvider.convertMessages(messages),
        tools: OpenAICompatibleProvider.convertTools(tools),
      } satisfies ChatRequestBody),
    });

    if (!response.ok) {
      throw new Error(`API returned error status ${response.status}`);
    }

    const json = (await response.json()) as ChatResponseBody;
    return convertChoice(json);
  }

  async streamChat(
    messages: Message[],
    tools: ToolDefinition[],
    onEvent: StreamEventHandler,
  ): Promise<AssistantTurn> {
    const response = await fetch(`${this.#baseUrl}/chat/completions`, {
      method: "POST",
      headers: this.#headers(),
      body: JSON.stringify({
        model: this.#model,
        messages: OpenAICompatibleProvider.convertMessages(messages),
        tools: OpenAICompatibleProvider.convertTools(tools),
        stream: true,
      } satisfies ChatRequestBody),
    });

    if (!response.ok || !response.body) {
      throw new Error(`API returned error status ${response.status}`);
    }

    const decoder = new TextDecoder();
    const reader = response.body.getReader();
    const accumulator = new StreamAccumulator();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex >= 0) {
        const line = buffer.slice(0, newlineIndex).replace(/\r$/, "");
        buffer = buffer.slice(newlineIndex + 1);
        newlineIndex = buffer.indexOf("\n");

        if (line.length === 0) {
          continue;
        }

        const events = parseSseLine(line);
        if (!events) {
          continue;
        }

        for (const event of events) {
          accumulator.feed(event);
          await onEvent(event);
        }
      }
    }

    return accumulator.finish();
  }

  #headers(): HeadersInit {
    return {
      "content-type": "application/json",
      authorization: `Bearer ${this.#apiKey}`,
    };
  }
}

function convertChoice(response: ChatResponseBody): AssistantTurn {
  const choice = response.choices[0];
  if (!choice) {
    throw new Error("no choices");
  }

  const toolCalls: ToolCall[] = (choice.message.tool_calls ?? []).map((call) => ({
    id: call.id,
    name: call.function.name,
    arguments: parseJsonOrNull(call.function.arguments),
  }));

  return {
    text: choice.message.content ?? undefined,
    toolCalls,
    stopReason: choice.finish_reason === "tool_calls" ? "tool_use" : "stop",
  };
}

function parseJsonOrNull(input: string): JsonValue {
  try {
    return JSON.parse(input) as JsonValue;
  } catch {
    return null;
  }
}

function readRequiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}
