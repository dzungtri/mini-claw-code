import { describe, expect, test } from "bun:test";
import { AskTool, MockInputHandler } from "../tools";

describe("AskTool", () => {
  test("delegates to the input handler", async () => {
    const tool = new AskTool(new MockInputHandler(["TypeScript"]));
    await expect(
      tool.call({
        question: "What language?",
        options: ["Rust", "TypeScript"],
      }),
    ).resolves.toBe("TypeScript");
  });
});
