import { describe, expect, test } from "bun:test";

import { AskTool, MockInputHandler } from "../src/tools";

describe("chapter 11", () => {
  test("AskTool delegates to the input handler", async () => {
    const tool = new AskTool(new MockInputHandler(["Rust", "TypeScript"]));
    await expect(
      tool.call({
        question: "What language?",
        options: ["Rust", "TypeScript"],
      }),
    ).resolves.toBe("Rust");
  });
});
