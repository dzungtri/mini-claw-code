import type { AssistantTurn, Message, Provider, ToolDefinition } from "../types";

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

type ChatResponse = {
  choices: Array<{
    message: {
      content?: string;
      tool_calls?: ApiToolCall[];
    };
    finish_reason?: string;
  }>;
};

/**
 * Chapter 6 exercise:
 * send an OpenAI-compatible chat-completions request with fetch.
 */
export class OpenAICompatibleProvider implements Provider {
  constructor(
    readonly apiKey: string,
    readonly model: string,
    readonly baseUrl = "https://api.openai.com/v1",
  ) {}

  static new(
    apiKey: string,
    model: string,
    baseUrl?: string,
  ): OpenAICompatibleProvider {
    return new OpenAICompatibleProvider(apiKey, model, baseUrl);
  }

  withBaseUrl(_url: string): OpenAICompatibleProvider {
    throw new Error("TODO(ch6): return a cloned provider with a new base URL");
  }

  static fromEnv(_model = "gpt-4.1-mini"): OpenAICompatibleProvider {
    throw new Error(
      "TODO(ch6): read OPENAI_API_KEY or GEMINI_API_KEY from the environment and construct the provider",
    );
  }

  static convertMessages(_messages: Message[]): ApiMessage[] {
    throw new Error(
      "TODO(ch6): convert internal messages into OpenAI-compatible API messages",
    );
  }

  static convertTools(_tools: ToolDefinition[]): ApiTool[] {
    throw new Error(
      "TODO(ch6): convert ToolDefinition values into API tool definitions",
    );
  }

  async chat(
    _messages: Message[],
    _tools: ToolDefinition[],
  ): Promise<AssistantTurn> {
    void ({} as ChatRequest);
    void ({} as ChatResponse);
    throw new Error(
      "TODO(ch6): POST to /chat/completions, parse the response, and convert it into an AssistantTurn",
    );
  }
}
