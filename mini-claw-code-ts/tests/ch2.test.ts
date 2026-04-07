import { describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { ReadTool } from "../src/tools/read";

describe("chapter 2", () => {
  test("ReadTool reads file contents", async () => {
    const dir = await mkdtemp(join(tmpdir(), "mini-claw-read-"));
    const path = join(dir, "hello.txt");
    await writeFile(path, "hello from bun", "utf8");

    try {
      const tool = new ReadTool();
      await expect(tool.call({ path })).resolves.toBe("hello from bun");
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});
