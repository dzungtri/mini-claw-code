import { ToolDefinition, ToolSet, assistantMessage, systemMessage, toolResultMessage, userMessage, type JsonObject, type Provider, type Tool } from "./types";

export class SubagentTool<P extends Provider> implements Tool {
  readonly #provider: P;
  readonly #toolsFactory: () => ToolSet;
  #systemPrompt?: string;
  #maxTurns = 10;
  readonly #definition: ToolDefinition;

  constructor(provider: P, toolsFactory: () => ToolSet) {
    this.#provider = provider;
    this.#toolsFactory = toolsFactory;
    this.#definition = new ToolDefinition(
      "subagent",
      "Spawn a child agent to handle a subtask independently.",
    ).param("task", "string", "A clear description of the subtask.", true);
  }

  static new<P extends Provider>(
    provider: P,
    toolsFactory: () => ToolSet,
  ): SubagentTool<P> {
    return new SubagentTool(provider, toolsFactory);
  }

  definition(): ToolDefinition {
    return this.#definition;
  }

  systemPrompt(prompt: string): this {
    this.#systemPrompt = prompt;
    return this;
  }

  maxTurns(value: number): this {
    this.#maxTurns = value;
    return this;
  }

  async call(args: JsonObject | null): Promise<string> {
    const task = args?.task;
    if (typeof task !== "string" || task.trim().length === 0) {
      throw new Error("missing required parameter: task");
    }

    const tools = this.#toolsFactory();
    const definitions = tools.definitions();
    const messages = [];

    if (this.#systemPrompt) {
      messages.push(systemMessage(this.#systemPrompt));
    }
    messages.push(userMessage(task));

    for (let turnIndex = 0; turnIndex < this.#maxTurns; turnIndex += 1) {
      const turn = await this.#provider.chat(messages, definitions);
      if (turn.stopReason === "stop") {
        return turn.text ?? "";
      }

      const results: Array<[string, string]> = [];
      for (const call of turn.toolCalls) {
        const tool = tools.get(call.name);
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

    return "error: max turns exceeded";
  }
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
