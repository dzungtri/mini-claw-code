from pathlib import Path
import importlib.util


def _load_tui_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "tui.py"
    spec = importlib.util.spec_from_file_location("mini_claw_code_py_examples_tui", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ch9_spinner_line_contains_label() -> None:
    tui = _load_tui_module()
    line = tui.spinner_line(0, "Thinking...")
    assert "Thinking..." in line
    assert "⠋" in line


def test_ch9_render_tool_line_collapses_after_threshold() -> None:
    tui = _load_tui_module()
    direct = tui.render_tool_line(1, "    [read: file.txt]")
    collapsed = tui.render_tool_line(tui.COLLAPSE_AFTER + 1, "ignored")
    assert "[read: file.txt]" in direct
    assert "... and 1 more" in collapsed


def test_ch9_prompt_prefix_changes_in_plan_mode() -> None:
    tui = _load_tui_module()
    assert "[plan]" in tui.prompt_prefix(True)
    assert "[plan]" not in tui.prompt_prefix(False)
