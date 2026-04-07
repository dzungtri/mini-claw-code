import { describe, expect, test } from "bun:test";
import { mkdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { BashTool, EditTool, ReadTool, WriteTool } from "../tools";

describe("tools", () => {
  test("ReadTool reads a file", async () => {
    const path = join(tmpdir(), "mini-claw-code-ts-read.txt");
    await Bun.write(path, "hello");
    await expect(new ReadTool().call({ path })).resolves.toBe("hello");
  });

  test("WriteTool creates directories", async () => {
    const path = join(tmpdir(), "mini-claw-code-ts", "nested", "write.txt");
    await expect(new WriteTool().call({ path, content: "hello" })).resolves.toContain("wrote");
    await expect(readFile(path, "utf8")).resolves.toBe("hello");
  });

  test("EditTool replaces exactly one match", async () => {
    const path = join(tmpdir(), "mini-claw-code-ts-edit.txt");
    await Bun.write(path, "hello world");
    await expect(
      new EditTool().call({
        path,
        old_string: "world",
        new_string: "typescript",
      }),
    ).resolves.toContain("edited");
    await expect(readFile(path, "utf8")).resolves.toBe("hello typescript");
  });

  test("BashTool captures stdout", async () => {
    const result = await new BashTool().call({ command: "echo hello" });
    expect(result).toContain("hello");
  });
});
