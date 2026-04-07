import { readFile, writeFile } from "node:fs/promises";

import type { JsonValue, Tool } from "../types";
import { ToolDefinition } from "../types";

export class EditTool implements Tool {
  readonly toolDefinition: ToolDefinition;

  constructor() {
    this.toolDefinition = ToolDefinition.new(
      "edit",
      "Replace an exact string in a file (must appear exactly once).",
    )
      .param("path", "string", "The file path to edit", true)
      .param("oldString", "string", "The exact string to find and replace", true)
      .param("newString", "string", "The replacement string", true);
  }

  static new(): EditTool {
    return new EditTool();
  }

  definition(): ToolDefinition {
    return this.toolDefinition;
  }

  async call(_args: JsonValue): Promise<string> {
    void readFile;
    void writeFile;
    throw new Error(
      "TODO(ch4): read the file, ensure oldString appears exactly once, write the replacement, and confirm success",
    );
  }
}
