from __future__ import annotations

import asyncio
from typing import Any

from ..types import ToolDefinition


class BashTool:
    def __init__(self) -> None:
        self._definition = ToolDefinition.new(
            "bash",
            "Run a bash command and return its output.",
        ).param("command", "string", "The bash command to run", True)

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        command = args.get("command") if isinstance(args, dict) else None
        if not isinstance(command, str):
            raise ValueError("missing 'command' argument")

        process = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"stderr: {stderr}")
        if not parts:
            return "(no output)"
        return "\n".join(parts)
