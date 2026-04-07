import { describe, expect, test } from "bun:test";

import { MockProvider } from "../src/mock";
import { SubagentTool } from "../src/subagent";
import { ToolSet } from "../src/types";

describe("chapter 13", () => {
  test("SubagentTool runs a child task to completion", async () => {
    const provider = new MockProvider([{ text: "child complete", toolCalls: [], stopReason: "stop" }]);
    const tool = SubagentTool.new(provider, () => new ToolSet());
    await expect(tool.call({ task: "do work" })).resolves.toBe("child complete");
  });
});
