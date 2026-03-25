from pathlib import Path

import pytest

from mini_claw_code_starter_py import ReadTool


def test_ch2_read_definition() -> None:
    tool = ReadTool.new()
    assert tool.definition.name == "read"
    assert "path" in tool.definition.parameters["required"]


@pytest.mark.asyncio
async def test_ch2_read_file(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world")
    tool = ReadTool.new()
    result = await tool.call({"path": str(path)})
    assert result == "hello world"
