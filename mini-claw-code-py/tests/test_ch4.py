from pathlib import Path

import pytest

from mini_claw_code_py import BashTool, EditTool, WriteTool


@pytest.mark.asyncio
async def test_ch4_bash_runs_command() -> None:
    result = await BashTool().call({"command": "echo hello"})
    assert "hello" in result


@pytest.mark.asyncio
async def test_ch4_bash_captures_stderr() -> None:
    result = await BashTool().call({"command": "echo err >&2"})
    assert "stderr:" in result
    assert "err" in result


@pytest.mark.asyncio
async def test_ch4_bash_no_output() -> None:
    assert await BashTool().call({"command": "true"}) == "(no output)"


@pytest.mark.asyncio
async def test_ch4_write_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    await WriteTool().call({"path": str(path), "content": "hello"})
    assert path.read_text() == "hello"


@pytest.mark.asyncio
async def test_ch4_write_creates_dirs(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "c" / "out.txt"
    await WriteTool().call({"path": str(path), "content": "hello"})
    assert path.read_text() == "hello"


@pytest.mark.asyncio
async def test_ch4_edit_replaces_string(tmp_path: Path) -> None:
    path = tmp_path / "edit.txt"
    path.write_text("hello world")
    await EditTool().call({"path": str(path), "old_string": "hello", "new_string": "goodbye"})
    assert path.read_text() == "goodbye world"


@pytest.mark.asyncio
async def test_ch4_edit_not_found(tmp_path: Path) -> None:
    path = tmp_path / "edit.txt"
    path.write_text("hello world")
    with pytest.raises(ValueError):
        await EditTool().call({"path": str(path), "old_string": "missing", "new_string": "x"})

