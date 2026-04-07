import { $ } from "bun";
import { ToolDefinition, type JsonObject, type Tool } from "../types";

export class BashTool implements Tool {
  readonly #definition = new ToolDefinition(
    "bash",
    "Run a bash command and return its output.",
  ).param("command", "string", "The bash command to run", true);

  definition(): ToolDefinition {
    return this.#definition;
  }

  async call(args: JsonObject | null): Promise<string> {
    const command = args?.command;
    if (typeof command !== "string") {
      throw new Error("missing 'command' argument");
    }

    const proc = Bun.spawn({
      cmd: ["bash", "-lc", command],
      stdout: "pipe",
      stderr: "pipe",
    });

    const stdout = await new Response(proc.stdout).text();
    const stderr = await new Response(proc.stderr).text();
    await proc.exited;

    const parts: string[] = [];
    if (stdout.trimEnd().length > 0) {
      parts.push(stdout.trimEnd());
    }
    if (stderr.trimEnd().length > 0) {
      parts.push(`stderr: ${stderr.trimEnd()}`);
    }

    return parts.length > 0 ? parts.join("\n") : "(no output)";
  }
}
