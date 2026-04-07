import { describe, expect, test } from "bun:test";

import { BashTool, EditTool, WriteTool } from "../src/tools";

describe("chapter 4: more tools", () => {
  test("bash exposes a command parameter", () => {
    expect(BashTool.new().definition().parameters.required).toContain("command");
  });

  test("write exposes path and content parameters", () => {
    const required = WriteTool.new().definition().parameters.required;
    expect(required).toContain("path");
    expect(required).toContain("content");
  });

  test("edit exposes path, oldString, and newString parameters", () => {
    const required = EditTool.new().definition().parameters.required;
    expect(required).toContain("path");
    expect(required).toContain("oldString");
    expect(required).toContain("newString");
  });
});
