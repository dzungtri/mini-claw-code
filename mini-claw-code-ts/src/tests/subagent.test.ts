import { describe, expect, test } from "bun:test";
import { MockProvider } from "../mock";
import { SubagentTool } from "../subagent";
import { ToolSet } from "../types";

describe("SubagentTool", () => {
  test("returns the child result", async () => {
    const tool = new SubagentTool(
      new MockProvider([{ text: "child done", toolCalls: [], stopReason: "stop" }]),
      () => new ToolSet(),
    );
    await expect(tool.call({ task: "do work" })).resolves.toBe("child done");
  });
});
