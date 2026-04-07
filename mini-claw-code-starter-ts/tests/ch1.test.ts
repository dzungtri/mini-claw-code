import { describe, expect, test } from "bun:test";

import { MockProvider } from "../src/mock";
import type { AssistantTurn } from "../src/types";

describe("chapter 1: MockProvider", () => {
  test("returns queued responses in order", async () => {
    const provider = MockProvider.new([
      {
        text: "first",
        toolCalls: [],
        stopReason: "stop",
      } satisfies AssistantTurn,
      {
        text: "second",
        toolCalls: [],
        stopReason: "stop",
      } satisfies AssistantTurn,
    ]);

    const first = await provider.chat([], []);
    const second = await provider.chat([], []);

    expect(first.text).toBe("first");
    expect(second.text).toBe("second");
  });
});
