import { describe, expect, test } from "bun:test";
import { MockProvider } from "../mock";
import { singleTurn, SimpleAgent } from "../agent";
import { ReadTool } from "../tools/read";
import { ToolDefinition, ToolSet, userMessage, type AssistantTurn } from "../types";

describe("core agent loop", () => {
  test("mock provider steps through responses", async () => {
    const provider = new MockProvider([
      { text: "first", toolCalls: [], stopReason: "stop" },
      { text: "second", toolCalls: [], stopReason: "stop" },
    ]);

    await expect(provider.chat([], [])).resolves.toMatchObject({ text: "first" });
    await expect(provider.chat([], [])).resolves.toMatchObject({ text: "second" });
  });

  test("singleTurn handles a direct response", async () => {
    const provider = new MockProvider([{ text: "hello", toolCalls: [], stopReason: "stop" }]);
    const result = await singleTurn(provider, new ToolSet(), "hi");
    expect(result).toBe("hello");
  });

  test("singleTurn executes a tool call", async () => {
    const path = "/tmp/mini-claw-code-ts-single-turn.txt";
    await Bun.write(path, "file content");

    const provider = new MockProvider([
      {
        toolCalls: [{ id: "call_1", name: "read", arguments: { path } }],
        stopReason: "tool_use",
      },
      { text: "done", toolCalls: [], stopReason: "stop" },
    ]);

    const result = await singleTurn(provider, ToolSet.from(new ReadTool()), "read");
    expect(result).toBe("done");
  });

  test("SimpleAgent loops until stop", async () => {
    const path = "/tmp/mini-claw-code-ts-agent.txt";
    await Bun.write(path, "alpha");

    const provider = new MockProvider([
      {
        toolCalls: [{ id: "call_1", name: "read", arguments: { path } }],
        stopReason: "tool_use",
      },
      { text: "alpha loaded", toolCalls: [], stopReason: "stop" },
    ]);

    const agent = new SimpleAgent(provider).tool(new ReadTool());
    const result = await agent.run("read");
    expect(result).toBe("alpha loaded");
  });

  test("ToolDefinition builds JSON schema", () => {
    const definition = new ToolDefinition("read", "Read a file").param(
      "path",
      "string",
      "The file path",
      true,
    );
    expect(definition.parameters.properties).toMatchObject({
      path: { type: "string", description: "The file path" },
    });
  });
});
