import { assistantMessage, systemMessage, toolResultMessage, ToolDefinition, ToolSet, type Message, type Tool } from "./types";
import type { StreamProvider } from "./streaming";
import type { AgentEventHandler } from "./agent";
import { toolSummary } from "./agent";
import { DEFAULT_PLAN_PROMPT_TEMPLATE } from "./prompts";

export class PlanAgent<P extends StreamProvider> {
  readonly provider: P;
  readonly tools: ToolSet;
  readonly readOnly: Set<string>;
  planSystemPrompt: string;
  readonly exitPlanDefinition: ToolDefinition;

  constructor(provider: P, tools = new ToolSet()) {
    this.provider = provider;
    this.tools = tools;
    this.readOnly = new Set(["bash", "read", "ask_user"]);
    this.planSystemPrompt = DEFAULT_PLAN_PROMPT_TEMPLATE;
    this.exitPlanDefinition = new ToolDefinition(
      "exit_plan",
      "Signal that your plan is complete and ready for user review.",
    );
  }

  static new<P extends StreamProvider>(provider: P): PlanAgent<P> {
    return new PlanAgent(provider);
  }

  tool(tool: Tool): this {
    this.tools.push(tool);
    return this;
  }

  readOnlyTools(names: string[]): this {
    this.readOnly.clear();
    for (const name of names) {
      this.readOnly.add(name);
    }
    return this;
  }

  planPrompt(prompt: string): this {
    this.planSystemPrompt = prompt;
    return this;
  }

  async plan(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {
    if (messages[0]?.kind !== "system") {
      messages.unshift(systemMessage(this.planSystemPrompt));
    }
    return this.runLoop(messages, this.readOnly, onEvent);
  }

  async execute(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {
    return this.runLoop(messages, undefined, onEvent);
  }

  private async runLoop(
    messages: Message[],
    allowed: Set<string> | undefined,
    onEvent?: AgentEventHandler,
  ): Promise<string> {
    const allDefinitions = this.tools.definitions();
    const definitions =
      allowed === undefined
        ? allDefinitions
        : [
            ...allDefinitions.filter((definition) => allowed.has(definition.name)),
            this.exitPlanDefinition,
          ];

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

      let exitPlan = false;
      const results: Array<[string, string]> = [];

      for (const call of turn.toolCalls) {
        if (allowed && call.name === "exit_plan") {
          results.push([call.id, "Plan submitted for review."]);
          exitPlan = true;
          continue;
        }

        if (allowed && !allowed.has(call.name)) {
          results.push([
            call.id,
            `error: tool '${call.name}' is not available in planning mode`,
          ]);
          continue;
        }

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

      const planText = turn.text ?? "";
      messages.push(assistantMessage(turn));
      for (const [id, content] of results) {
        messages.push(toolResultMessage(id, content));
      }

      if (exitPlan) {
        await onEvent?.({ kind: "done", text: planText });
        return planText;
      }
    }
  }
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
