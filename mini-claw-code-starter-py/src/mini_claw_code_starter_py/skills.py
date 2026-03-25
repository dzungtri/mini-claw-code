from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


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
    """Chapter 14: parse a SKILL.md file into a Skill."""

    raise NotImplementedError(
        "Read the file, split YAML frontmatter from the markdown body, validate "
        "the required fields, and return a Skill"
    )


def default_skill_roots(
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Chapter 14: discover default skill roots in user and project locations."""

    raise NotImplementedError(
        "Return skill roots in discovery order so user skills load first and "
        "deeper project-local skills override them later"
    )


class SkillRegistry:
    def __init__(self, skills: dict[str, Skill] | None = None) -> None:
        self._skills = skills or {}

    @classmethod
    def discover(cls, roots: Iterable[Path]) -> "SkillRegistry":
        raise NotImplementedError(
            "Scan each root for SKILL.md files, parse them, and store them by "
            "skill name with later roots overriding earlier ones"
        )

    @classmethod
    def discover_default(
        cls,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "SkillRegistry":
        raise NotImplementedError(
            "Call default_skill_roots(...) and then reuse discover(...)"
        )

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda skill: skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def prompt_section(self) -> str:
        raise NotImplementedError(
            "Render the structured <skill_system> prompt block with "
            "<available_skills> entries for each discovered skill"
        )
