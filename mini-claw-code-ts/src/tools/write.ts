import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { ToolDefinition, type JsonObject, type Tool } from "../types";

export class WriteTool implements Tool {
  readonly #definition = new ToolDefinition(
    "write",
    "Write content to a file, creating directories as needed.",
  )
    .param("path", "string", "The file path to write to", true)
    .param("content", "string", "The content to write to the file", true);

  definition(): ToolDefinition {
    return this.#definition;
  }

  async call(args: JsonObject | null): Promise<string> {
    const path = args?.path;
    const content = args?.content;

    if (typeof path !== "string") {
      throw new Error("missing 'path' argument");
    }
    if (typeof content !== "string") {
      throw new Error("missing 'content' argument");
    }

    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content, "utf8");
    return `wrote ${path}`;
  }
}
