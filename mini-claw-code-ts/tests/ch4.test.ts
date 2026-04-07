import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { BashTool, EditTool, WriteTool } from "../src/tools";

describe("chapter 4", () => {
  test("WriteTool and EditTool update files", async () => {
    const dir = await mkdtemp(join(tmpdir(), "mini-claw-write-"));
    const path = join(dir, "nested", "note.txt");

    try {
      const writer = new WriteTool();
      const editor = new EditTool();

      await expect(writer.call({ path, content: "hello world" })).resolves.toBe(`wrote ${path}`);
      await expect(
        editor.call({ path, old_string: "world", new_string: "bun" }),
      ).resolves.toBe(`edited ${path}`);
      await expect(readFile(path, "utf8")).resolves.toBe("hello bun");
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  test("BashTool captures stdout", async () => {
    const tool = new BashTool();
    await expect(tool.call({ command: "printf 'hi'" })).resolves.toBe("hi");
  });
});
