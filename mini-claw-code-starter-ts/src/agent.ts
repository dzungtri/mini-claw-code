import type {
  AssistantTurn,
  JsonValue,
  Message,
  Provider,
  Tool,
  ToolCall,
  ToolSet,
} from "./types";
import { ToolSet as ToolSetImpl } from "./types";

export function toolSummary(call: ToolCall): string {
  const args =
    typeof call.arguments === "object" &&
    call.arguments !== null &&
    !Array.isArray(call.arguments)
      ? (call.arguments as Record<string, JsonValue>)
      : null;
  const detail =
    typeof args?.command === "string"
      ? args.command
      : typeof args?.path === "string"
        ? args.path
        : undefined;

  return detail ? `    [${call.name}: ${detail}]` : `    [${call.name}]`;
}

/**
 * Chapter 3 exercise:
 * one provider request, maybe one round of tool calls, then a final answer.
 */
export async function singleTurn(
  _provider: Provider,
  _tools: ToolSet,
  _prompt: string,
): Promise<string> {
  throw new Error(
    "TODO(ch3): call the provider, match on stopReason, run tools, then ask for the final answer",
  );
}

export class SimpleAgent {
  readonly tools: ToolSet;

  constructor(
    readonly provider: Provider,
    tools?: ToolSet,
  ) {
    this.tools = tools ?? ToolSetImpl.new();
  }

  static new(provider: Provider): SimpleAgent {
    return new SimpleAgent(provider);
  }

  tool(_tool: Tool): SimpleAgent {
    throw new Error("TODO(ch5): register the tool and return this");
  }

  async run(_prompt: string): Promise<string> {
    throw new Error(
      "TODO(ch5): build the agent loop that continues until stopReason === 'stop'",
    );
  }

  async chat(_messages: Message[]): Promise<string> {
    throw new Error(
      "TODO(ch7): reuse the run loop with an existing conversation history",
    );
  }

  protected async executeTools(
    turn: AssistantTurn,
  ): Promise<Array<{ id: string; content: string }>> {
    const results: Array<{ id: string; content: string }> = [];

    for (const call of turn.toolCalls) {
      const tool = this.tools.get(call.name);
      if (!tool) {
        results.push({
          id: call.id,
          content: `error: unknown tool \`${call.name}\``,
        });
        continue;
      }

      try {
        results.push({
          id: call.id,
          content: await tool.call(call.arguments),
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "unknown tool error";
        results.push({
          id: call.id,
          content: `error: ${message}`,
        });
      }
    }

    return results;
  }
}
