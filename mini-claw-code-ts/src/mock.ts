import type { AssistantTurn, Message, Provider, ToolDefinition } from "./types";

export class MockProvider implements Provider {
  #responses: AssistantTurn[];
  #cursor = 0;

  constructor(responses: Iterable<AssistantTurn>) {
    this.#responses = [...responses];
  }

  async chat(_messages: Message[], _tools: ToolDefinition[]): Promise<AssistantTurn> {
    const turn = this.#responses[this.#cursor];
    if (!turn) {
      throw new Error("MockProvider: no more responses");
    }

    this.#cursor += 1;
    return structuredClone(turn);
  }
}
