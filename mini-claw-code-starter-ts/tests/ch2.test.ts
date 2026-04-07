import { describe, expect, test } from "bun:test";

import { ReadTool } from "../src/tools/read";

describe("chapter 2: ReadTool", () => {
  test("declares a required path parameter", () => {
    const tool = ReadTool.new();
    const definition = tool.definition();

    expect(definition.name).toBe("read");
    expect(definition.parameters.required).toContain("path");
  });
});
