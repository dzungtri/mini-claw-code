import { describe, expect, test } from "bun:test";

import { singleTurn, SimpleAgent } from "../src/agent";
import { MockProvider } from "../src/mock";
import { ToolSet } from "../src/types";
import { ReadTool } from "../src/tools/read";

describe("chapter 3", () => {
  test("singleTurn returns the provider text response", async () => {
    const provider = new MockProvider([{ text: "done", toolCalls: [], stopReason: "stop" }]);
    await expect(singleTurn(provider, new ToolSet(), "hello")).resolves.toBe("done");
  });

  test("SimpleAgent runs until stop", async () => {
    const provider = new MockProvider([{ text: "done", toolCalls: [], stopReason: "stop" }]);
    const agent = SimpleAgent.new(provider).tool(new ReadTool());
    await expect(agent.run("hello")).resolves.toBe("done");
  });
});
