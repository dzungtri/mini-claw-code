import { spawn } from "node:child_process";

import type { JsonValue, Tool } from "../types";
import { ToolDefinition } from "../types";

export class BashTool implements Tool {
  readonly toolDefinition: ToolDefinition;

  constructor() {
    this.toolDefinition = ToolDefinition.new(
      "bash",
      "Run a bash command and return its output.",
    ).param("command", "string", "The bash command to run", true);
  }

  static new(): BashTool {
    return new BashTool();
  }

  definition(): ToolDefinition {
    return this.toolDefinition;
  }

  async call(_args: JsonValue): Promise<string> {
    void spawn;
    throw new Error(
      "TODO(ch4): run `bash -lc`, collect stdout/stderr, and return a combined string",
    );
  }
}
