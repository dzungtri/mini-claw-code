from __future__ import annotations

from typing import Any

from ..types import ToolDefinition


class EditTool:
    def __init__(self) -> None:
        self._definition = None

    @property
    def definition(self) -> ToolDefinition:
        if self._definition is None:
            raise RuntimeError("EditTool.new() must initialize self._definition")
        return self._definition

    @classmethod
    def new(cls) -> "EditTool":
        raise NotImplementedError(
            "Define an edit tool with required 'path', 'old_string', and 'new_string' parameters"
        )

    async def call(self, args: Any) -> str:
        raise NotImplementedError(
            "Replace exactly one occurrence of old_string in the target file and return a confirmation"
        )
