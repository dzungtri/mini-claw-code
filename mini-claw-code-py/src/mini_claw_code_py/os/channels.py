from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .work import TeamRegistry


CHANNEL_CONFIG_FILE_NAME = ".channels.json"


@dataclass(slots=True)
class ChannelDefinition:
    name: str
    description: str
    default_target_agent: str | None = None
    default_team: str | None = None
    thread_prefix: str | None = None

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.description = " ".join(self.description.split()).strip() or f"Channel {self.name}"
        self.default_target_agent = (
            None if self.default_target_agent is None else self.default_target_agent.strip() or None
        )
        self.default_team = None if self.default_team is None else self.default_team.strip() or None
        self.thread_prefix = self.name if self.thread_prefix is None else self.thread_prefix.strip() or self.name
        if not self.name:
            raise ValueError("channel name cannot be empty")
        if self.default_target_agent is None and self.default_team is None:
            self.default_target_agent = "superagent"

    def resolve_target_agent(self, teams: TeamRegistry | None = None) -> str:
        if self.default_target_agent is not None:
            return self.default_target_agent
        if self.default_team is None or teams is None:
            raise ValueError(f"channel {self.name} cannot resolve a default target agent")
        return teams.require(self.default_team).lead_agent

    def resolve_thread_key(self, suffix: str) -> str:
        normalized = suffix.strip() or "default"
        return f"{self.thread_prefix}:{normalized}"


class ChannelRegistry:
    def __init__(self, channels: Mapping[str, ChannelDefinition] | None = None) -> None:
        self._channels = dict(channels or {})

    @classmethod
    def discover(cls, paths: list[Path]) -> "ChannelRegistry":
        merged: dict[str, dict[str, object]] = {}
        for path in paths:
            for name, raw in _parse_channel_registry_raw(path).items():
                current = merged.get(name, {})
                merged[name] = {**current, **raw}
        channels = {name: _channel_from_raw(name, raw) for name, raw in merged.items()}
        if "cli" not in channels:
            channels["cli"] = default_cli_channel()
        return cls(channels)

    @classmethod
    def discover_default(
        cls,
        *,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "ChannelRegistry":
        return cls.discover(default_channel_config_paths(cwd=cwd, home=home))

    def all(self) -> list[ChannelDefinition]:
        return [self._channels[name] for name in sorted(self._channels)]

    def get(self, name: str) -> ChannelDefinition | None:
        return self._channels.get(name)

    def require(self, name: str) -> ChannelDefinition:
        channel = self.get(name)
        if channel is None:
            raise KeyError(f"unknown channel: {name}")
        return channel

    def render(self) -> str:
        if not self._channels:
            return "Channels: none."
        lines = ["Channels:"]
        for channel in self.all():
            target = channel.default_target_agent if channel.default_target_agent is not None else f"team:{channel.default_team}"
            lines.append(f"- {channel.name}: {channel.description}")
            lines.append(f"  target={target}")
            lines.append(f"  thread_prefix={channel.thread_prefix}")
        return "\n".join(lines)


def default_cli_channel() -> ChannelDefinition:
    return ChannelDefinition(
        name="cli",
        description="Local front-door terminal channel.",
        default_target_agent="superagent",
        thread_prefix="cli",
    )


def default_channel_config_paths(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    target_home = Path.home() if home is None else Path(home)
    paths: list[Path] = []
    home_path = (target_home / CHANNEL_CONFIG_FILE_NAME).expanduser().resolve()
    if home_path.exists():
        paths.append(home_path)
    project_path = (target_cwd / CHANNEL_CONFIG_FILE_NAME).expanduser().resolve()
    if project_path.exists() and project_path != home_path:
        paths.append(project_path)
    return paths


def parse_channel_registry(path: str | Path) -> dict[str, ChannelDefinition]:
    return {name: _channel_from_raw(name, raw) for name, raw in _parse_channel_registry_raw(path).items()}


def _parse_channel_registry_raw(path: str | Path) -> dict[str, dict[str, object]]:
    config_path = Path(path).expanduser().resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"channel registry must contain a JSON object: {config_path}")
    channels = raw.get("channels", {})
    if not isinstance(channels, dict):
        raise ValueError("channels must be an object")
    parsed: dict[str, dict[str, object]] = {}
    for name, value in channels.items():
        if not isinstance(name, str):
            raise ValueError("channel names must be strings")
        if not isinstance(value, dict):
            raise ValueError(f"channel definition must be an object: {name}")
        parsed[name.strip()] = _normalize_channel_raw(name, value)
    return parsed


def _normalize_channel_raw(name: str, value: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    if "description" in value:
        description = value["description"]
        if not isinstance(description, str):
            raise ValueError(f"description must be a string: {name}")
        normalized["description"] = description
    if "default_target_agent" in value:
        agent = value["default_target_agent"]
        if agent is not None and not isinstance(agent, str):
            raise ValueError(f"default_target_agent must be a string: {name}")
        normalized["default_target_agent"] = agent
    if "default_team" in value:
        team = value["default_team"]
        if team is not None and not isinstance(team, str):
            raise ValueError(f"default_team must be a string: {name}")
        normalized["default_team"] = team
    if "thread_prefix" in value:
        prefix = value["thread_prefix"]
        if prefix is not None and not isinstance(prefix, str):
            raise ValueError(f"thread_prefix must be a string: {name}")
        normalized["thread_prefix"] = prefix
    return normalized


def _channel_from_raw(name: str, raw: Mapping[str, object]) -> ChannelDefinition:
    return ChannelDefinition(
        name=name,
        description=str(raw.get("description", f"Channel {name}")),
        default_target_agent=raw.get("default_target_agent") if raw.get("default_target_agent") is None else str(raw.get("default_target_agent")),
        default_team=raw.get("default_team") if raw.get("default_team") is None else str(raw.get("default_team")),
        thread_prefix=raw.get("thread_prefix") if raw.get("thread_prefix") is None else str(raw.get("thread_prefix")),
    )
