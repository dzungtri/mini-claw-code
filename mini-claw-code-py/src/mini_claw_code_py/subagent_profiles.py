from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SUBAGENT_CONFIG_FILE_NAME = ".subagents.json"


@dataclass(slots=True)
class SubagentProfile:
    name: str
    description: str
    system_prompt: str | None = None
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    max_turns: int | None = None


class SubagentProfileRegistry:
    def __init__(self, profiles: dict[str, SubagentProfile] | None = None) -> None:
        self._profiles = profiles or {}

    @classmethod
    def discover(
        cls,
        paths: Iterable[Path],
    ) -> "SubagentProfileRegistry":
        profiles: dict[str, SubagentProfile] = {}
        for path in paths:
            if not path.is_file():
                continue
            for profile in parse_subagent_config(path):
                profiles[profile.name] = profile
        return cls(profiles)

    @classmethod
    def discover_default(
        cls,
        *,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "SubagentProfileRegistry":
        return cls.discover(default_subagent_config_paths(cwd=cwd, home=home))

    def all(self) -> list[SubagentProfile]:
        return sorted(self._profiles.values(), key=lambda profile: profile.name)

    def get(self, name: str) -> SubagentProfile | None:
        return self._profiles.get(name)

    def is_empty(self) -> bool:
        return not self._profiles

    def prompt_section(self) -> str:
        profiles = self.all()
        if not profiles:
            return ""
        lines = [
            "<configured_subagents>",
            "Available configured subagent types:",
        ]
        for profile in profiles:
            lines.append(f"- {profile.name}: {profile.description}")
        lines.append("Use `subagent_type` when a configured specialist is a better fit than the general-purpose child.")
        lines.append("</configured_subagents>")
        return "\n".join(lines)

    def render(self) -> str:
        profiles = self.all()
        if not profiles:
            return "Subagent profiles: none."
        lines = ["Subagent profiles:"]
        for profile in profiles:
            tools = ", ".join(profile.tools) if profile.tools else "inherit default child tools"
            skills = ", ".join(profile.skills) if profile.skills else "none"
            max_turns = str(profile.max_turns) if profile.max_turns is not None else "inherit"
            lines.append(f"- {profile.name}: {profile.description}")
            lines.append(f"  tools: {tools}")
            lines.append(f"  skills: {skills}")
            lines.append(f"  max_turns: {max_turns}")
        return "\n".join(lines)


def default_subagent_config_paths(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    target_cwd = (cwd or Path.cwd()).resolve()
    target_home = (home or Path.home()).expanduser().resolve()
    ordered = [target_home / SUBAGENT_CONFIG_FILE_NAME]
    project = _nearest_project_subagent_config(target_cwd)
    if project is not None and project not in ordered:
        ordered.append(project)
    return ordered


def parse_subagent_config(path: Path) -> list[SubagentProfile]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: config must be a JSON object")
    subagents = raw.get("subagents")
    if not isinstance(subagents, dict):
        raise ValueError(f"{path}: missing required 'subagents' object")
    profiles: list[SubagentProfile] = []
    for name, spec in subagents.items():
        profiles.append(_parse_profile(path, name, spec))
    return sorted(profiles, key=lambda profile: profile.name)


def _parse_profile(path: Path, name: object, spec: object) -> SubagentProfile:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}: subagent names must be non-empty strings")
    if not isinstance(spec, dict):
        raise ValueError(f"{path}: subagent '{name}' must be a JSON object")
    description = spec.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{path}: subagent '{name}' requires a string description")
    system_prompt = spec.get("system_prompt")
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise ValueError(f"{path}: subagent '{name}' field 'system_prompt' must be a string")
    tools = _string_list(path, name, spec.get("tools"), "tools")
    skills = _string_list(path, name, spec.get("skills"), "skills")
    max_turns = spec.get("max_turns")
    if max_turns is not None:
        if not isinstance(max_turns, int) or max_turns < 1:
            raise ValueError(f"{path}: subagent '{name}' field 'max_turns' must be a positive integer")
    return SubagentProfile(
        name=name.strip(),
        description=description.strip(),
        system_prompt=system_prompt.strip() if isinstance(system_prompt, str) and system_prompt.strip() else None,
        tools=tuple(tools),
        skills=tuple(skills),
        max_turns=max_turns,
    )


def _string_list(
    path: Path,
    name: str,
    value: object,
    field_name: str,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{path}: subagent '{name}' field '{field_name}' must be a list of non-empty strings")
    return [item.strip() for item in value]


def _nearest_project_subagent_config(start: Path) -> Path | None:
    if start.is_file():
        start = start.parent
    for base in [start, *start.parents]:
        candidate = base / SUBAGENT_CONFIG_FILE_NAME
        if candidate.is_file():
            return candidate
    return None
