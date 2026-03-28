from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from ..config import apply_harness_config, load_harness_config
from ..prompts import (
    DEFAULT_PLAN_PROMPT_TEMPLATE,
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    SYSTEM_PROMPT_FILE_ENV,
    load_prompt_template,
    render_system_prompt,
)
from ..tools import ChannelInputHandler, UserInputRequest

if TYPE_CHECKING:
    import asyncio

    from ..harness import HarnessAgent
    from ..providers import OpenRouterProvider


AGENT_REGISTRY_FILE_NAME = ".agents.json"


@dataclass(slots=True)
class HostedAgentDefinition:
    name: str
    description: str
    workspace_root: Path
    default_channels: tuple[str, ...] = ("cli",)
    config_path: Path | None = None
    remote_endpoint: str | None = None

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.description = " ".join(self.description.split()).strip() or f"Hosted agent {self.name}"
        self.workspace_root = Path(self.workspace_root).expanduser().resolve()
        if self.config_path is not None:
            self.config_path = Path(self.config_path).expanduser().resolve()
        self.default_channels = tuple(channel.strip() for channel in self.default_channels if channel.strip())
        if not self.name:
            raise ValueError("agent name cannot be empty")
        if not self.default_channels:
            self.default_channels = ("cli",)


@dataclass(slots=True)
class HostedAgentFactory:
    provider: "OpenRouterProvider"
    home: Path
    input_queue: "asyncio.Queue[UserInputRequest]"
    env: Mapping[str, str] | None = None

    def build(self, definition: HostedAgentDefinition) -> "HarnessAgent":
        from ..harness import HarnessAgent

        system_prompt = render_system_prompt(
            load_prompt_template(
                SYSTEM_PROMPT_FILE_ENV,
                DEFAULT_SYSTEM_PROMPT_TEMPLATE,
            ),
            cwd=definition.workspace_root,
        )
        plan_prompt = render_system_prompt(
            DEFAULT_PLAN_PROMPT_TEMPLATE,
            cwd=definition.workspace_root,
        )
        agent = HarnessAgent(self.provider).system_prompt(system_prompt).plan_prompt(plan_prompt)
        config = load_harness_config(
            cwd=definition.workspace_root,
            home=self.home,
            env=self.env if self.env is not None else os.environ,
            config_path=definition.config_path,
        )
        apply_harness_config(
            agent,
            config,
            handler=ChannelInputHandler(self.input_queue),
        )
        return agent


class HostedAgentRegistry:
    def __init__(self, agents: Mapping[str, HostedAgentDefinition] | None = None) -> None:
        self._agents = dict(agents or {})

    @classmethod
    def discover(
        cls,
        paths: list[Path],
        *,
        cwd: Path,
    ) -> "HostedAgentRegistry":
        merged: dict[str, dict[str, object]] = {}
        for path in paths:
            for name, raw in _parse_agent_registry_raw(path).items():
                current = merged.get(name, {})
                merged[name] = {**current, **raw}
        agents = {
            name: _definition_from_raw(name, raw, default_workspace_root=cwd)
            for name, raw in merged.items()
        }
        if "superagent" not in agents:
            agents["superagent"] = default_superagent_definition(cwd)
        return cls(agents)

    @classmethod
    def discover_default(
        cls,
        *,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "HostedAgentRegistry":
        target_cwd = Path.cwd() if cwd is None else Path(cwd)
        target_home = Path.home() if home is None else Path(home)
        return cls.discover(default_agent_registry_paths(cwd=target_cwd, home=target_home), cwd=target_cwd)

    def all(self) -> list[HostedAgentDefinition]:
        return [self._agents[name] for name in sorted(self._agents)]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))

    def get(self, name: str) -> HostedAgentDefinition | None:
        return self._agents.get(name)

    def require(self, name: str) -> HostedAgentDefinition:
        definition = self.get(name)
        if definition is None:
            raise KeyError(f"unknown hosted agent: {name}")
        return definition

    def render(self, *, current_agent: str | None = None) -> str:
        if not self._agents:
            return "Hosted agents: none."
        lines = ["Hosted agents:"]
        for definition in self.all():
            marker = " [active]" if definition.name == current_agent else ""
            lines.append(f"- {definition.name}{marker}: {definition.description}")
            lines.append(f"  workspace={definition.workspace_root}")
            lines.append(f"  channels={', '.join(definition.default_channels)}")
            if definition.config_path is not None:
                lines.append(f"  config={definition.config_path}")
            if definition.remote_endpoint:
                lines.append(f"  remote_endpoint={definition.remote_endpoint}")
        return "\n".join(lines)


def default_agent_registry_paths(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    target_home = Path.home() if home is None else Path(home)
    paths: list[Path] = []
    home_path = (target_home / AGENT_REGISTRY_FILE_NAME).expanduser().resolve()
    if home_path.exists():
        paths.append(home_path)
    project_path = (target_cwd / AGENT_REGISTRY_FILE_NAME).expanduser().resolve()
    if project_path.exists() and project_path != home_path:
        paths.append(project_path)
    return paths


def parse_agent_registry(path: str | Path) -> dict[str, HostedAgentDefinition]:
    return {
        name: _definition_from_raw(name, raw, default_workspace_root=Path.cwd())
        for name, raw in _parse_agent_registry_raw(path).items()
    }


def default_superagent_definition(cwd: Path | None = None) -> HostedAgentDefinition:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    return HostedAgentDefinition(
        name="superagent",
        description="Default front-door hosted agent.",
        workspace_root=target_cwd,
        default_channels=("cli",),
    )


def _resolve_registry_path(raw: object, base_dir: Path) -> Path:
    if not isinstance(raw, str):
        raise ValueError("registry path values must be strings")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (base_dir / candidate).resolve()


def _parse_agent_registry_raw(path: str | Path) -> dict[str, dict[str, object]]:
    import json

    config_path = Path(path).expanduser().resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"agent registry must contain a JSON object: {config_path}")
    agents = raw.get("agents", {})
    if not isinstance(agents, dict):
        raise ValueError("agents must be an object")
    parsed: dict[str, dict[str, object]] = {}
    for name, value in agents.items():
        if not isinstance(name, str):
            raise ValueError("agent names must be strings")
        if not isinstance(value, dict):
            raise ValueError(f"agent definition must be an object: {name}")
        parsed[name.strip()] = _normalize_agent_raw(name, value, base_dir=config_path.parent)
    return parsed


def _normalize_agent_raw(name: str, value: dict[str, object], *, base_dir: Path) -> dict[str, object]:
    normalized: dict[str, object] = {}
    if "description" in value:
        description = value["description"]
        if not isinstance(description, str):
            raise ValueError(f"description must be a string: {name}")
        normalized["description"] = description
    if "workspace_root" in value:
        normalized["workspace_root"] = _resolve_registry_path(value["workspace_root"], base_dir)
    if "default_channels" in value:
        channels = value["default_channels"]
        if not isinstance(channels, list) and not isinstance(channels, tuple):
            raise ValueError(f"default_channels must be a list: {name}")
        normalized["default_channels"] = tuple(str(channel) for channel in channels)
    if "config_path" in value:
        config_ref = value["config_path"]
        if config_ref is not None and not isinstance(config_ref, str):
            raise ValueError(f"config_path must be a string: {name}")
        normalized["config_path"] = (
            _resolve_registry_path(config_ref, base_dir)
            if config_ref is not None
            else None
        )
    if "remote_endpoint" in value:
        remote_endpoint = value["remote_endpoint"]
        if remote_endpoint is not None and not isinstance(remote_endpoint, str):
            raise ValueError(f"remote_endpoint must be a string: {name}")
        normalized["remote_endpoint"] = remote_endpoint
    return normalized


def _definition_from_raw(
    name: str,
    raw: Mapping[str, object],
    *,
    default_workspace_root: Path,
) -> HostedAgentDefinition:
    return HostedAgentDefinition(
        name=name,
        description=str(raw.get("description", f"Hosted agent {name}")),
        workspace_root=Path(raw.get("workspace_root", default_workspace_root)),
        default_channels=tuple(raw.get("default_channels", ("cli",))),  # type: ignore[arg-type]
        config_path=Path(raw["config_path"]) if raw.get("config_path") is not None else None,
        remote_endpoint=str(raw["remote_endpoint"]) if raw.get("remote_endpoint") is not None else None,
    )
