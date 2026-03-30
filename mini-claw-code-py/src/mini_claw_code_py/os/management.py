from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..mcp import MCPServer
from .agent_registry import AGENT_REGISTRY_FILE_NAME, HostedAgentDefinition
from .channels import CHANNEL_CONFIG_FILE_NAME, ChannelDefinition
from .work import TEAM_CONFIG_FILE_NAME, TeamDefinition


def add_hosted_agent(
    *,
    cwd: Path,
    definition: HostedAgentDefinition,
) -> Path:
    path = (Path(cwd).resolve() / AGENT_REGISTRY_FILE_NAME).resolve()
    raw = _read_config(path)
    agents = _require_object(raw, "agents")
    agents[definition.name] = _serialize_agent(definition, base_dir=path.parent)
    _write_config(path, raw)
    return path


def add_team(
    *,
    cwd: Path,
    definition: TeamDefinition,
) -> Path:
    path = (Path(cwd).resolve() / TEAM_CONFIG_FILE_NAME).resolve()
    raw = _read_config(path)
    teams = _require_object(raw, "teams")
    teams[definition.name] = _serialize_team(definition, base_dir=path.parent)
    _write_config(path, raw)
    return path


def add_channel(
    *,
    cwd: Path,
    definition: ChannelDefinition,
) -> Path:
    path = (Path(cwd).resolve() / CHANNEL_CONFIG_FILE_NAME).resolve()
    raw = _read_config(path)
    channels = _require_object(raw, "channels")
    channels[definition.name] = _serialize_channel(definition)
    _write_config(path, raw)
    return path


def add_mcp_server(
    *,
    cwd: Path,
    server: MCPServer,
) -> Path:
    path = (Path(cwd).resolve() / ".mcp.json").resolve()
    raw = _read_config(path)
    servers = _require_object(raw, "mcpServers")
    servers[server.name] = server.to_config()
    _write_config(path, raw)
    return path


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config must contain a JSON object: {path}")
    return raw


def _require_object(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        raw[key] = {}
        value = raw[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _write_config(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(raw, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _serialize_agent(definition: HostedAgentDefinition, *, base_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": definition.description,
        "workspace_root": _make_relative_if_possible(definition.workspace_root, base_dir=base_dir),
        "default_channels": list(definition.default_channels),
    }
    if definition.config_path is not None:
        payload["config_path"] = _make_relative_if_possible(definition.config_path, base_dir=base_dir)
    if definition.remote_endpoint is not None:
        payload["remote_endpoint"] = definition.remote_endpoint
    return payload


def _serialize_team(definition: TeamDefinition, *, base_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": definition.description,
        "lead_agent": definition.lead_agent,
        "member_agents": list(definition.member_agents),
    }
    if definition.workspace_root is not None:
        payload["workspace_root"] = _make_relative_if_possible(definition.workspace_root, base_dir=base_dir)
    return payload


def _serialize_channel(definition: ChannelDefinition) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": definition.description,
        "thread_prefix": definition.thread_prefix,
    }
    if definition.default_target_agent is not None:
        payload["default_target_agent"] = definition.default_target_agent
    if definition.default_team is not None:
        payload["default_team"] = definition.default_team
    return payload


def _make_relative_if_possible(path: Path, *, base_dir: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(base_dir))
    except ValueError:
        return str(resolved)
