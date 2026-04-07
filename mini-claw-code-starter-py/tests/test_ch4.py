from pathlib import Path

import pytest

from mini_claw_code_starter_py import BashTool, EditTool, WriteTool


@pytest.mark.asyncio
async def test_ch4_bash_runs_command() -> None:
    result = await BashTool.new().call({"command": "echo hello"})
    assert "hello" in result


@pytest.mark.asyncio
async def test_ch4_write_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    await WriteTool.new().call({"path": str(path), "content": "hello"})
    assert path.read_text() == "hello"


@pytest.mark.asyncio
async def test_ch4_edit_replaces_string(tmp_path: Path) -> None:
    path = tmp_path / "edit.txt"
    path.write_text("hello world")
    await EditTool.new().call(
        {"path": str(path), "old_string": "hello", "new_string": "goodbye"}
    )
    assert path.read_text() == "goodbye world"
