import {
  assistantMessage,
  toolResultMessage,
  ToolSet,
  userMessage,
  type AssistantTurn,
  type Message,
  type Provider,
  type ToolCall,
} from "./types";

export type AgentEvent =
  | { kind: "text_delta"; text: string }
  | { kind: "tool_call"; name: string; summary: string }
  | { kind: "done"; text: string }
  | { kind: "error"; error: string };

export type AgentEventHandler = (event: AgentEvent) => void | Promise<void>;

async function emit(handler: AgentEventHandler | undefined, event: AgentEvent): Promise<void> {
  if (handler) {
    await handler(event);
  }
}

export function toolSummary(call: ToolCall): string {
  const argumentsObject =
    call.arguments && typeof call.arguments === "object" && !Array.isArray(call.arguments)
      ? call.arguments
      : undefined;

  const detail = [
    argumentsObject?.command,
    argumentsObject?.path,
    argumentsObject?.question,
  ].find((value): value is string => typeof value === "string");

  return detail ? `    [${call.name}: ${detail}]` : `    [${call.name}]`;
}

async function executeTools(tools: ToolSet, calls: ToolCall[]): Promise<Array<[string, string]>> {
  const results: Array<[string, string]> = [];

  for (const call of calls) {
    const tool = tools.get(call.name);
    const content = tool
      ? await tool.call(call.arguments).catch((error) => `error: ${toErrorMessage(error)}`)
      : `error: unknown tool \`${call.name}\``;
    results.push([call.id, content]);
  }

  return results;
}

function pushResults(
  messages: Message[],
  turn: AssistantTurn,
  results: Array<[string, string]>,
): void {
  messages.push(assistantMessage(turn));
  for (const [id, content] of results) {
    messages.push(toolResultMessage(id, content));
  }
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function singleTurn(
  provider: Provider,
  tools: ToolSet,
  prompt: string,
): Promise<string> {
  const definitions = tools.definitions();
  const messages: Message[] = [userMessage(prompt)];
  const turn = await provider.chat(messages, definitions);

  if (turn.stopReason === "stop") {
    return turn.text ?? "";
  }

  const results = await executeTools(tools, turn.toolCalls);
  pushResults(messages, turn, results);
  const finalTurn = await provider.chat(messages, definitions);
  return finalTurn.text ?? "";
}

export class SimpleAgent<P extends Provider> {
  readonly provider: P;
  readonly tools: ToolSet;

  constructor(provider: P, tools = new ToolSet()) {
    this.provider = provider;
    this.tools = tools;
  }

  static new<P extends Provider>(provider: P): SimpleAgent<P> {
    return new SimpleAgent(provider);
  }

  tool(tool: Parameters<ToolSet["push"]>[0]): this {
    this.tools.push(tool);
    return this;
  }

  async run(prompt: string): Promise<string> {
    const messages: Message[] = [userMessage(prompt)];
    return this.chat(messages);
  }

  async chat(messages: Message[]): Promise<string> {
    const definitions = this.tools.definitions();

    for (;;) {
      const turn = await this.provider.chat(messages, definitions);

      if (turn.stopReason === "stop") {
        const text = turn.text ?? "";
        messages.push(assistantMessage(turn));
        return text;
      }

      const results = await executeTools(this.tools, turn.toolCalls);
      pushResults(messages, turn, results);
    }
  }

  async runWithHistory(messages: Message[], onEvent?: AgentEventHandler): Promise<Message[]> {
    const definitions = this.tools.definitions();

    for (;;) {
      let turn: AssistantTurn;
      try {
        turn = await this.provider.chat(messages, definitions);
      } catch (error) {
        await emit(onEvent, { kind: "error", error: toErrorMessage(error) });
        return messages;
      }

      if (turn.stopReason === "stop") {
        const text = turn.text ?? "";
        messages.push(assistantMessage(turn));
        await emit(onEvent, { kind: "done", text });
        return messages;
      }

      for (const call of turn.toolCalls) {
        await emit(onEvent, {
          kind: "tool_call",
          name: call.name,
          summary: toolSummary(call),
        });
      }

      const results = await executeTools(this.tools, turn.toolCalls);
      pushResults(messages, turn, results);
    }
  }

  async runWithEvents(prompt: string, onEvent: AgentEventHandler): Promise<void> {
    await this.runWithHistory([userMessage(prompt)], onEvent);
  }
}
