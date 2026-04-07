import { describe, expect, test } from "bun:test";

import { MockProvider } from "../src/mock";
import { SimpleAgent } from "../src/agent";

describe("chapter 5: agent loop", () => {
  test("runs until the model stops", async () => {
    const agent = SimpleAgent.new(
      MockProvider.new([
        {
          text: "done",
          toolCalls: [],
          stopReason: "stop",
        },
      ]),
    );

    const result = await agent.run("hello");
    expect(result).toBe("done");
  });
});
