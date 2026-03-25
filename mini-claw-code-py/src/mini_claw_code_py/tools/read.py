from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..types import ToolDefinition


class ReadTool:
    def __init__(self) -> None:
        self._definition = ToolDefinition.new(
            "read",
            "Read the contents of a file.",
        ).param("path", "string", "The file path to read", True)

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        path = args.get("path") if isinstance(args, dict) else None
        if not isinstance(path, str):
            raise ValueError("missing 'path' argument")
        try:
            return await asyncio.to_thread(Path(path).read_text)
        except Exception as exc:
            raise RuntimeError(f"failed to read '{path}'") from exc
