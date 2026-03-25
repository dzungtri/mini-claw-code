from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..types import ToolDefinition


class EditTool:
    def __init__(self) -> None:
        self._definition = (
            ToolDefinition.new(
                "edit",
                "Replace an exact string in a file (must appear exactly once).",
            )
            .param("path", "string", "The file path to edit", True)
            .param("old_string", "string", "The exact string to find and replace", True)
            .param("new_string", "string", "The replacement string", True)
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        path = args.get("path") if isinstance(args, dict) else None
        old = args.get("old_string") if isinstance(args, dict) else None
        new = args.get("new_string") if isinstance(args, dict) else None
        if not isinstance(path, str):
            raise ValueError("missing 'path' argument")
        if not isinstance(old, str):
            raise ValueError("missing 'old_string' argument")
        if not isinstance(new, str):
            raise ValueError("missing 'new_string' argument")

        path_obj = Path(path)
        try:
            content = await asyncio.to_thread(path_obj.read_text)
        except Exception as exc:
            raise RuntimeError(f"failed to read '{path}'") from exc

        count = content.count(old)
        if count == 0:
            raise ValueError(f"old_string not found in '{path}'")
        if count > 1:
            raise ValueError(f"old_string appears {count} times in '{path}', must be unique")

        updated = content.replace(old, new, 1)
        try:
            await asyncio.to_thread(path_obj.write_text, updated)
        except Exception as exc:
            raise RuntimeError(f"failed to write '{path}'") from exc

        return f"edited {path}"
