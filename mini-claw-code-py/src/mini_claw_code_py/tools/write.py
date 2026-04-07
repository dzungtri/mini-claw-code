from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..types import ToolDefinition


class WriteTool:
    def __init__(self) -> None:
        self._definition = (
            ToolDefinition.new(
                "write",
                "Write content to a file, creating directories as needed.",
            )
            .param("path", "string", "The file path to write to", True)
            .param("content", "string", "The content to write to the file", True)
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        path = args.get("path") if isinstance(args, dict) else None
        content = args.get("content") if isinstance(args, dict) else None
        if not isinstance(path, str):
            raise ValueError("missing 'path' argument")
        if not isinstance(content, str):
            raise ValueError("missing 'content' argument")

        path_obj = Path(path)
        if path_obj.parent:
            await asyncio.to_thread(path_obj.parent.mkdir, parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(path_obj.write_text, content)
        except Exception as exc:
            raise RuntimeError(f"failed to write '{path}'") from exc
        return f"wrote {path}"
