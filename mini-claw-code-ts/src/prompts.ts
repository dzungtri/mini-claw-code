import { readFile } from "node:fs/promises";

export const DEFAULT_SYSTEM_PROMPT_TEMPLATE = await Bun.file(
  new URL("../prompts/prompt.md", import.meta.url),
).text();

export const DEFAULT_PLAN_PROMPT_TEMPLATE = await Bun.file(
  new URL("../prompts/planning_prompt.md", import.meta.url),
).text();

export const SYSTEM_PROMPT_FILE_ENV = "MINI_CLAW_TS_SYSTEM_PROMPT_FILE";
export const PLAN_PROMPT_FILE_ENV = "MINI_CLAW_TS_PLAN_PROMPT_FILE";

export async function loadPromptTemplate(
  envVar: string,
  defaultTemplate: string,
): Promise<string> {
  const path = process.env[envVar]?.trim();
  if (!path) {
    return defaultTemplate;
  }

  try {
    return await readFile(path, "utf8");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`failed to read prompt file from ${envVar}=${path}: ${message}`);
  }
}
