import { assistantMessage, toolResultMessage, ToolSet, userMessage, type AssistantTurn, type JsonValue, type Message, type ToolCall, type ToolDefinition } from "./types";
import type { AgentEventHandler } from "./agent";
import { toolSummary } from "./agent";
import type { Provider } from "./types";

export type StreamEvent =
  | { kind: "text_delta"; text: string }
  | { kind: "tool_call_start"; index: number; id: string; name: string }
  | { kind: "tool_call_delta"; index: number; arguments: string }
  | { kind: "done" };

export type StreamEventHandler = (event: StreamEvent) => void | Promise<void>;

export interface StreamProvider {
  streamChat(
    messages: Message[],
    tools: ToolDefinition[],
    onEvent: StreamEventHandler,
  ): Promise<AssistantTurn>;
}

interface PartialToolCall {
  id: string;
  name: string;
  arguments: string;
}

export class StreamAccumulator {
  #text = "";
  #toolCalls: PartialToolCall[] = [];

  feed(event: StreamEvent): void {
    switch (event.kind) {
      case "text_delta":
        this.#text += event.text;
        return;
      case "tool_call_start":
        while (this.#toolCalls.length <= event.index) {
          this.#toolCalls.push({ id: "", name: "", arguments: "" });
        }
        this.#toolCalls[event.index] = {
          ...this.#toolCalls[event.index]!,
          id: event.id,
          name: event.name,
        };
        return;
      case "tool_call_delta":
        this.#toolCalls[event.index] ??= { id: "", name: "", arguments: "" };
        this.#toolCalls[event.index]!.arguments += event.arguments;
        return;
      case "done":
        return;
    }
  }

  finish(): AssistantTurn {
    const toolCalls: ToolCall[] = this.#toolCalls
      .filter((toolCall) => toolCall.name.length > 0)
      .map((toolCall) => ({
        id: toolCall.id,
        name: toolCall.name,
        arguments: parseJsonOrNull(toolCall.arguments),
      }));

    return {
      text: this.#text.length > 0 ? this.#text : undefined,
      toolCalls,
      stopReason: toolCalls.length > 0 ? "tool_use" : "stop",
    };
  }
}

export function parseSseLine(line: string): StreamEvent[] | undefined {
  if (!line.startsWith("data: ")) {
    return undefined;
  }

  const data = line.slice(6);
  if (data === "[DONE]") {
    return [{ kind: "done" }];
  }

  const chunk = parseJsonOrNull(data) as {
    choices?: Array<{
      delta?: {
        content?: string;
        tool_calls?: Array<{
          index: number;
          id?: string;
          function?: { name?: string; arguments?: string };
        }>;
      };
    }>;
  } | null;

  const delta = chunk?.choices?.[0]?.delta;
  if (!delta) {
    return undefined;
  }

  const events: StreamEvent[] = [];

  if (delta.content) {
    events.push({ kind: "text_delta", text: delta.content });
  }

  for (const call of delta.tool_calls ?? []) {
    if (call.id) {
      events.push({
        kind: "tool_call_start",
        index: call.index,
        id: call.id,
        name: call.function?.name ?? "",
      });
    }
    if (call.function?.arguments) {
      events.push({
        kind: "tool_call_delta",
        index: call.index,
        arguments: call.function.arguments,
      });
    }
  }

  return events.length > 0 ? events : undefined;
}

export class MockStreamProvider implements StreamProvider {
  readonly #provider: Provider;

  constructor(provider: Provider) {
    this.#provider = provider;
  }

  async streamChat(
    messages: Message[],
    tools: ToolDefinition[],
    onEvent: StreamEventHandler,
  ): Promise<AssistantTurn> {
    const turn = await this.#provider.chat(messages, tools);

    for (const character of turn.text ?? "") {
      await onEvent({ kind: "text_delta", text: character });
    }

    for (const [index, call] of turn.toolCalls.entries()) {
      await onEvent({
        kind: "tool_call_start",
        index,
        id: call.id,
        name: call.name,
      });
      await onEvent({
        kind: "tool_call_delta",
        index,
        arguments: JSON.stringify(call.arguments),
      });
    }

    await onEvent({ kind: "done" });
    return turn;
  }
}

export class StreamingAgent<P extends StreamProvider> {
  readonly provider: P;
  readonly tools: ToolSet;

  constructor(provider: P, tools = new ToolSet()) {
    this.provider = provider;
    this.tools = tools;
  }

  static new<P extends StreamProvider>(provider: P): StreamingAgent<P> {
    return new StreamingAgent(provider);
  }

  tool(tool: Parameters<ToolSet["push"]>[0]): this {
    this.tools.push(tool);
    return this;
  }

  async run(prompt: string, onEvent?: AgentEventHandler): Promise<string> {
    const messages = [userMessage(prompt)];
    return this.chat(messages, onEvent);
  }

  async chat(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {
    const definitions = this.tools.definitions();

    for (;;) {
      const turn = await this.provider.streamChat(messages, definitions, async (event) => {
        if (event.kind === "text_delta") {
          await onEvent?.({ kind: "text_delta", text: event.text });
        }
      });

      if (turn.stopReason === "stop") {
        const text = turn.text ?? "";
        messages.push(assistantMessage(turn));
        await onEvent?.({ kind: "done", text });
        return text;
      }

      const results: Array<[string, string]> = [];
      for (const call of turn.toolCalls) {
        await onEvent?.({
          kind: "tool_call",
          name: call.name,
          summary: toolSummary(call),
        });
        const tool = this.tools.get(call.name);
        const content = tool
          ? await tool.call(call.arguments).catch((error) => `error: ${toErrorMessage(error)}`)
          : `error: unknown tool \`${call.name}\``;
        results.push([call.id, content]);
      }

      messages.push(assistantMessage(turn));
      for (const [id, content] of results) {
        messages.push(toolResultMessage(id, content));
      }
    }
  }
}

function parseJsonOrNull(input: string): JsonValue {
  try {
    return JSON.parse(input) as JsonValue;
  } catch {
    return null;
  }
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
