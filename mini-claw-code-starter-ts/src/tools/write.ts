import { mkdir, writeFile } from "node:fs/promises";

import type { JsonValue, Tool } from "../types";
import { ToolDefinition } from "../types";

export class WriteTool implements Tool {
  readonly toolDefinition: ToolDefinition;

  constructor() {
    this.toolDefinition = ToolDefinition.new(
      "write",
      "Write content to a file, creating directories as needed.",
    )
      .param("path", "string", "The file path to write to", true)
      .param("content", "string", "The content to write to the file", true);
  }

  static new(): WriteTool {
    return new WriteTool();
  }

  definition(): ToolDefinition {
    return this.toolDefinition;
  }

  async call(_args: JsonValue): Promise<string> {
    void mkdir;
    void writeFile;
    throw new Error(
      "TODO(ch4): extract path/content, create parent directories, write the file, and confirm success",
    );
  }
}
