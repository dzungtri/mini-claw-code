import { describe, expect, test } from "bun:test";
import { OpenAICompatibleProvider } from "../providers";
import { ToolDefinition, userMessage } from "../types";

describe("OpenAICompatibleProvider helpers", () => {
  test("convertMessages converts user and tool_result messages", () => {
    const converted = OpenAICompatibleProvider.convertMessages([
      userMessage("hello"),
      { kind: "tool_result", id: "call_1", content: "result" },
    ]);

    expect(converted).toHaveLength(2);
    expect(converted[0]).toMatchObject({ role: "user", content: "hello" });
    expect(converted[1]).toMatchObject({
      role: "tool",
      content: "result",
      tool_call_id: "call_1",
    });
  });

  test("convertTools serializes function definitions", () => {
    const tools = OpenAICompatibleProvider.convertTools([
      new ToolDefinition("read", "Read a file").param("path", "string", "path", true),
    ]);

    expect(tools[0]).toMatchObject({
      type: "function",
      function: {
        name: "read",
        description: "Read a file",
      },
    });
  });
});
