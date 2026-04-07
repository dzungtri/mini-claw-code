import { describe, expect, test } from "bun:test";

import { MockProvider } from "../src/mock";
import type { AssistantTurn } from "../src/types";

describe("chapter 1", () => {
  test("MockProvider returns canned responses in sequence", async () => {
    const responses: AssistantTurn[] = [
      { text: "first", toolCalls: [], stopReason: "stop" },
      { text: "second", toolCalls: [], stopReason: "stop" },
    ];
    const provider = new MockProvider(responses);

    await expect(provider.chat([], [])).resolves.toEqual(responses[0]!);
    await expect(provider.chat([], [])).resolves.toEqual(responses[1]!);
    await expect(provider.chat([], [])).rejects.toThrow("MockProvider: no more responses");
  });
});
