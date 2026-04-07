import type { AssistantTurn, Message, Provider, ToolDefinition } from "./types";

/**
 * Chapter 1 exercise:
 * return canned responses in FIFO order through the Provider interface.
 */
export class MockProvider implements Provider {
  constructor(private readonly responses: AssistantTurn[]) {
    void responses;
  }

  static new(responses: AssistantTurn[]): MockProvider {
    return new MockProvider(responses);
  }

  async chat(
    _messages: Message[],
    _tools: ToolDefinition[],
  ): Promise<AssistantTurn> {
    throw new Error(
      "TODO(ch1): consume the next canned response and throw when none remain",
    );
  }
}
