from pathlib import Path

import pytest

from mini_claw_code_py import ReadTool


def test_ch2_read_definition() -> None:
    tool = ReadTool()
    assert tool.definition.name == "read"
    assert "path" in tool.definition.parameters["required"]


@pytest.mark.asyncio
async def test_ch2_read_file(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world")
    result = await ReadTool().call({"path": str(path)})
    assert result == "hello world"


@pytest.mark.asyncio
async def test_ch2_read_missing_file() -> None:
    with pytest.raises(RuntimeError):
        await ReadTool().call({"path": "/tmp/__mini_claw_code_nonexistent_test_file__.txt"})


@pytest.mark.asyncio
async def test_ch2_read_missing_arg() -> None:
    with pytest.raises(ValueError):
        await ReadTool().call({})
