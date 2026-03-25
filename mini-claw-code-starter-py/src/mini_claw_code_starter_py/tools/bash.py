from __future__ import annotations

from typing import Any

from ..types import ToolDefinition


class BashTool:
    def __init__(self) -> None:
        self._definition = None

    @property
    def definition(self) -> ToolDefinition:
        if self._definition is None:
            raise RuntimeError("BashTool.new() must initialize self._definition")
        return self._definition

    @classmethod
    def new(cls) -> "BashTool":
        raise NotImplementedError(
            "Define a bash tool with one required 'command' string parameter"
        )

    async def call(self, args: Any) -> str:
        raise NotImplementedError(
            "Run bash -lc <command>, combine stdout and stderr, and return '(no output)' when empty"
        )
