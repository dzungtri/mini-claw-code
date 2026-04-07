import { describe, expect, test } from "bun:test";
import { MockProvider } from "../mock";
import { MockStreamProvider } from "../streaming";
import { PlanAgent } from "../planning";
import { ReadTool } from "../tools";
import { userMessage } from "../types";

describe("plan mode", () => {
  test("plan injects a system prompt", async () => {
    const provider = new MockStreamProvider(
      new MockProvider([{ text: "plan text", toolCalls: [], stopReason: "stop" }]),
    );
    const agent = new PlanAgent(provider).tool(new ReadTool());
    const messages = [userMessage("plan this")];
    const result = await agent.plan(messages);
    expect(result).toBe("plan text");
    expect(messages[0]?.kind).toBe("system");
  });
});
