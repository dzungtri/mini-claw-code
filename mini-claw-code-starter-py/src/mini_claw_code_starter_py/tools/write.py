from __future__ import annotations

from typing import Any

from ..types import ToolDefinition


class WriteTool:
    def __init__(self) -> None:
        self._definition = None

    @property
    def definition(self) -> ToolDefinition:
        if self._definition is None:
            raise RuntimeError("WriteTool.new() must initialize self._definition")
        return self._definition

    @classmethod
    def new(cls) -> "WriteTool":
        raise NotImplementedError(
            "Define a write tool with required 'path' and 'content' string parameters"
        )

    async def call(self, args: Any) -> str:
        raise NotImplementedError(
            "Extract path and content, create parent directories, write the file, and confirm"
        )
