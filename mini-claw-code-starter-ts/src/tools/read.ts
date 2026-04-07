import { readFile } from "node:fs/promises";

import type { JsonValue, Tool } from "../types";
import { ToolDefinition } from "../types";

export class ReadTool implements Tool {
  readonly toolDefinition: ToolDefinition;

  constructor() {
    this.toolDefinition = ToolDefinition.new(
      "read",
      "Read the contents of a file.",
    ).param("path", "string", "The file path to read", true);
  }

  static new(): ReadTool {
    return new ReadTool();
  }

  definition(): ToolDefinition {
    return this.toolDefinition;
  }

  async call(_args: JsonValue): Promise<string> {
    void readFile;
    throw new Error(
      "TODO(ch2): extract args.path, read the file, and return the contents",
    );
  }
}
