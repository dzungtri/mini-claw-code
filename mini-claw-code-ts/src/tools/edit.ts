import { readFile, writeFile } from "node:fs/promises";
import { ToolDefinition, type JsonObject, type Tool } from "../types";

export class EditTool implements Tool {
  readonly #definition = new ToolDefinition(
    "edit",
    "Replace an exact string in a file (must appear exactly once).",
  )
    .param("path", "string", "The file path to edit", true)
    .param("old_string", "string", "The exact string to find and replace", true)
    .param("new_string", "string", "The replacement string", true);

  definition(): ToolDefinition {
    return this.#definition;
  }

  async call(args: JsonObject | null): Promise<string> {
    const path = args?.path;
    const oldString = args?.old_string;
    const newString = args?.new_string;

    if (typeof path !== "string") {
      throw new Error("missing 'path' argument");
    }
    if (typeof oldString !== "string") {
      throw new Error("missing 'old_string' argument");
    }
    if (typeof newString !== "string") {
      throw new Error("missing 'new_string' argument");
    }

    const content = await readFile(path, "utf8");
    const matches = content.split(oldString).length - 1;
    if (matches === 0) {
      throw new Error(`old_string not found in '${path}'`);
    }
    if (matches > 1) {
      throw new Error(`old_string appears ${matches} times in '${path}', must be unique`);
    }

    await writeFile(path, content.replace(oldString, newString), "utf8");
    return `edited ${path}`;
  }
}
