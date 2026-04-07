import { readFile } from "node:fs/promises";
import { ToolDefinition, type JsonObject, type Tool } from "../types";

export class ReadTool implements Tool {
  readonly #definition = new ToolDefinition("read", "Read the contents of a file.").param(
    "path",
    "string",
    "The file path to read",
    true,
  );

  definition(): ToolDefinition {
    return this.#definition;
  }

  async call(args: JsonObject | null): Promise<string> {
    const path = args?.path;
    if (typeof path !== "string") {
      throw new Error("missing 'path' argument");
    }
    return readFile(path, "utf8");
  }
}
