from pathlib import Path

import pytest

from mini_claw_code_py import SkillRegistry, default_skill_roots, parse_skill_file, render_system_prompt


def _write_skill(
    root: Path,
    name: str,
    description: str,
    *,
    body: str = "# Demo\n",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"""---
name: {name}
description: {description}
---

{body}
""",
        encoding="utf-8",
    )
    return skill_file


def test_ch14_parse_skill_file() -> None:
    root = Path(__file__).resolve().parents[1] / ".agents" / "skills"
    skill = parse_skill_file(root / "python-packaging" / "SKILL.md")
    assert skill.name == "python-packaging"
    assert "publishing workflows" in skill.description
    assert "Workflow" in skill.instructions
    assert skill.resource_paths("references")


def test_ch14_rejects_invalid_skill(tmp_path: Path) -> None:
    skill_file = tmp_path / "broken" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        """---
name: Broken Skill
description: nope
---
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid skill name"):
        parse_skill_file(skill_file)


def test_ch14_allows_standard_optional_frontmatter(tmp_path: Path) -> None:
    skill_file = tmp_path / "demo-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        """---
name: demo-skill
description: Demo skill
license: MIT
version: 1.0.0
author: example/demo
argument-hint: optional
---

# Demo
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_file)

    assert skill.name == "demo-skill"
    assert skill.description == "Demo skill"


def test_ch14_project_skill_overrides_user_skill(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "workspace" / "demo"
    user_root = home / ".agents" / "skills"
    project_root = project / ".agents" / "skills"

    _write_skill(user_root, "python-packaging", "User skill")
    _write_skill(project_root, "python-packaging", "Project skill")

    registry = SkillRegistry.discover(default_skill_roots(cwd=project, home=home))
    skill = registry.get("python-packaging")

    assert skill is not None
    assert skill.description == "Project skill"
    assert skill.path == project_root / "python-packaging" / "SKILL.md"


def test_ch14_prompt_section_lists_skill_paths(tmp_path: Path) -> None:
    project_root = tmp_path / ".agents" / "skills"
    skill_file = _write_skill(project_root, "demo-skill", "Helpful workflow")

    registry = SkillRegistry.discover([project_root])
    section = registry.prompt_section()
    prompt = render_system_prompt(
        "Working directory: {{cwd}}",
        cwd=tmp_path,
        extra_sections=[section],
    )

    assert "<skill_system>" in section
    assert "<available_skills>" in section
    assert "<name>demo-skill</name>" in section
    assert f"<location>{skill_file}</location>" in section
    assert "immediately use the `read` tool" in section
    assert str(tmp_path) in prompt
