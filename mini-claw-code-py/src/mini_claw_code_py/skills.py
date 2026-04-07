from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


_SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$|^[a-z0-9]$")


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    path: Path
    instructions: str
    compatibility: Any = None
    metadata: dict[str, Any] | None = None

    @property
    def root(self) -> Path:
        return self.path.parent

    def resource_paths(self, directory: str) -> list[Path]:
        base = self.root / directory
        if not base.is_dir():
            return []
        return sorted(path for path in base.rglob("*") if path.is_file())


def parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(text)
    data = yaml.safe_load(frontmatter_text)

    if not isinstance(data, dict):
        raise ValueError(f"{path}: frontmatter must be a YAML object")

    name = data.get("name")
    description = data.get("description")
    compatibility = data.get("compatibility")
    metadata = data.get("metadata")

    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}: missing required 'name'")
    name = name.strip()
    if not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError(f"{path}: invalid skill name '{name}'")

    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{path}: missing required 'description'")
    description = description.strip()

    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"{path}: 'metadata' must be a mapping")

    return Skill(
        name=name,
        description=description,
        path=path,
        instructions=body.strip(),
        compatibility=compatibility,
        metadata=metadata,
    )


def default_skill_roots(
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    start = (cwd or Path.cwd()).resolve()
    user_home = (home or Path.home()).expanduser().resolve()

    roots = [user_home / ".agents" / "skills"]
    project_candidates = [base / ".agents" / "skills" for base in reversed([start, *start.parents])]

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in [*roots, *project_candidates]:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


class SkillRegistry:
    def __init__(self, skills: dict[str, Skill] | None = None) -> None:
        self._skills = skills or {}

    @classmethod
    def discover(cls, roots: Iterable[Path]) -> "SkillRegistry":
        skills: dict[str, Skill] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.rglob("SKILL.md")):
                skill = parse_skill_file(skill_file)
                skills[skill.name] = skill
        return cls(skills)

    @classmethod
    def discover_default(
        cls,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "SkillRegistry":
        return cls.discover(default_skill_roots(cwd=cwd, home=home))

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda skill: skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def prompt_section(self) -> str:
        skills = self.all()
        if not skills:
            return ""

        skill_items = "\n".join(
            "\n".join(
                [
                    "    <skill>",
                    f"        <name>{skill.name}</name>",
                    f"        <description>{skill.description}</description>",
                    f"        <location>{skill.path}</location>",
                    "    </skill>",
                ]
            )
            for skill in skills
        )

        lines = [
            "<skill_system>",
            "You have access to reusable skills stored in local SKILL.md files.",
            "Each skill contains an optimized workflow, best practices, and optional references.",
            "",
            "Progressive loading pattern:",
            "1. When a task clearly matches a skill, immediately use the `read` tool on that skill's SKILL.md file.",
            "2. Read and understand the workflow before acting.",
            "3. Load `references/` files only when the skill points you to them or you need more detail.",
            "4. Run `scripts/` only when they help you follow the skill reliably.",
            "5. Follow the skill instructions closely once you have loaded them.",
            "",
            "<available_skills>",
            skill_items,
            "</available_skills>",
            "",
            "</skill_system>",
        ]
        return "\n".join(lines)


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("skill file must start with YAML frontmatter")

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            return frontmatter, body

    raise ValueError("skill file is missing the closing frontmatter delimiter")
