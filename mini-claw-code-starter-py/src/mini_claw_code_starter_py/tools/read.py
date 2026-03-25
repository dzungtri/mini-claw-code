from __future__ import annotations

from typing import Any

from ..types import ToolDefinition


class ReadTool:
    """Chapter 2: build your first tool."""

    def __init__(self) -> None:
        self._definition = None

    @property
    def definition(self) -> ToolDefinition:
        if self._definition is None:
            raise RuntimeError("ReadTool.new() must initialize self._definition")
        return self._definition

    @classmethod
    def new(cls) -> "ReadTool":
        raise NotImplementedError(
            "Create a ToolDefinition named 'read' with a required 'path' parameter"
        )

    async def call(self, args: Any) -> str:
        raise NotImplementedError(
            "Extract 'path', read the file asynchronously, and return the contents"
        )
