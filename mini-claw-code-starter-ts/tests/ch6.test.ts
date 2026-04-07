import { describe, expect, test } from "bun:test";

import {
  OpenAICompatibleProvider,
} from "../src/providers/openai-compatible";
import { ToolDefinition } from "../src/types";

describe("chapter 6: HTTP provider", () => {
  test("converts tool definitions into API tools", () => {
    const tools = OpenAICompatibleProvider.convertTools([
      ToolDefinition.new("read", "Read a file").param(
        "path",
        "string",
        "The file path to read",
        true,
      ),
    ]);

    expect(tools[0]?.type).toBe("function");
    expect(tools[0]?.function.name).toBe("read");
  });
});
