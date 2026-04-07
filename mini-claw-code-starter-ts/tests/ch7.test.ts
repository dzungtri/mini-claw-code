import { describe, expect, test } from "bun:test";

import { SimpleAgent } from "../src/agent";
import { MockProvider } from "../src/mock";
import type { Message } from "../src/types";

describe("chapter 7: chat history", () => {
  test("appends a user message and returns the assistant reply", async () => {
    const agent = SimpleAgent.new(
      MockProvider.new([
        {
          text: "hello again",
          toolCalls: [],
          stopReason: "stop",
        },
      ]),
    );

    const history: Message[] = [{ kind: "user", text: "hi" }];
    const result = await agent.chat(history);

    expect(result).toBe("hello again");
  });
});
