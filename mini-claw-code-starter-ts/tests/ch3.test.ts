import { describe, expect, test } from "bun:test";

import { singleTurn } from "../src/agent";
import { MockProvider } from "../src/mock";
import { ToolSet } from "../src/types";

describe("chapter 3: singleTurn", () => {
  test("returns a direct assistant response", async () => {
    const provider = MockProvider.new([
      {
        text: "hello from the model",
        toolCalls: [],
        stopReason: "stop",
      },
    ]);

    const result = await singleTurn(provider, ToolSet.new(), "hi");
    expect(result).toBe("hello from the model");
  });
});
