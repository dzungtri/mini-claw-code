from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from fastmcp import Client

from .types import JSONValue, ToolDefinition


_ENV_VAR_RE = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_KNOWN_TRANSPORTS = {"stdio", "http", "sse"}


@dataclass(slots=True)
class MCPServer:
    name: str
    config_path: Path
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] | None = None
    oauth: dict[str, Any] | None = None
    headers_helper: str | None = None
    metadata: dict[str, Any] | None = None

    def summary(self) -> str:
        if self.transport == "stdio":
            if self.command is None:
                return "stdio MCP server"
            return f"Stdio MCP server via {self.command}"
        if self.transport == "http" and self.url is not None:
            return f"HTTP MCP server at {self.url}"
        if self.transport == "sse" and self.url is not None:
            return f"SSE MCP server at {self.url}"
        return f"{self.transport} MCP server"

    def to_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"type": self.transport}
        if self.command is not None:
            config["command"] = self.command
        if self.args:
            config["args"] = list(self.args)
        if self.env:
            config["env"] = dict(self.env)
        if self.url is not None:
            config["url"] = self.url
        if self.headers:
            config["headers"] = dict(self.headers)
        if self.oauth:
            config["oauth"] = dict(self.oauth)
        if self.headers_helper is not None:
            config["headersHelper"] = self.headers_helper
        if self.metadata:
            config.update(self.metadata)
        return config


def parse_mcp_config(
    path: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> list[MCPServer]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: config must be a JSON object")

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: missing required 'mcpServers' object")

    resolved_env = dict(os.environ if env is None else env)
    parsed = [_parse_server(path, name, config, resolved_env) for name, config in servers.items()]
    return sorted(parsed, key=lambda server: server.name)


def default_mcp_config_paths(
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    start = (cwd or Path.cwd()).resolve()
    user_home = (home or Path.home()).expanduser().resolve()

    ordered = [user_home / ".mcp.json"]
    project_config = _nearest_project_config(start)
    if project_config is not None and project_config not in ordered:
        ordered.append(project_config)
    return ordered


class MCPRegistry:
    def __init__(self, servers: dict[str, MCPServer] | None = None) -> None:
        self._servers = servers or {}

    @classmethod
    def discover(
        cls,
        paths: Iterable[Path],
        *,
        env: Mapping[str, str] | None = None,
    ) -> "MCPRegistry":
        servers: dict[str, MCPServer] = {}
        for path in paths:
            if not path.is_file():
                continue
            for server in parse_mcp_config(path, env=env):
                servers[server.name] = server
        return cls(servers)

    @classmethod
    def discover_default(
        cls,
        cwd: Path | None = None,
        home: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> "MCPRegistry":
        return cls.discover(default_mcp_config_paths(cwd=cwd, home=home), env=env)

    def all(self) -> list[MCPServer]:
        return sorted(self._servers.values(), key=lambda server: server.name)

    def get(self, name: str) -> MCPServer | None:
        return self._servers.get(name)

    def to_config(self) -> dict[str, Any]:
        return {
            "mcpServers": {
                server.name: server.to_config()
                for server in self.all()
            }
        }

    def prompt_section(self) -> str:
        servers = self.all()
        if not servers:
            return ""

        server_items = "\n".join(
            "\n".join(
                [
                    "    <server>",
                    f"        <name>{server.name}</name>",
                    f"        <transport>{server.transport}</transport>",
                    f"        <source>{server.config_path}</source>",
                    f"        <summary>{server.summary()}</summary>",
                    "    </server>",
                ]
            )
            for server in servers
        )

        lines = [
            "<mcp_system>",
            "You may be running with MCP servers configured in local `.mcp.json` files.",
            "Use this catalog to understand what external integrations exist.",
            "",
            "Guidelines:",
            "1. Prefer configured MCP integrations when the active runtime exposes their tools.",
            "2. If exact connection details matter, read the source `.mcp.json` file.",
            "3. Do not invent MCP tools that are not present in the active tool list.",
            "",
            "<configured_mcp_servers>",
            server_items,
            "</configured_mcp_servers>",
            "",
            "</mcp_system>",
        ]
        return "\n".join(lines)


class MCPToolProxy:
    def __init__(self, client: Client, definition: ToolDefinition) -> None:
        self._client = client
        self._definition = definition

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: JSONValue) -> str:
        arguments = args if isinstance(args, dict) else {}
        result = await self._client.call_tool(self._definition.name, arguments)
        return _stringify_tool_result(result)


class MCPToolAdapter:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._client: Client | None = None
        self._tools: list[MCPToolProxy] = []

    async def __aenter__(self) -> "MCPToolAdapter":
        if not self.registry.all():
            return self

        client = Client(self.registry.to_config())
        await client.__aenter__()
        self._client = client
        listed = await client.list_tools()
        self._tools = [
            MCPToolProxy(client, _tool_definition_from_mcp(tool))
            for tool in listed
        ]
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)
            self._client = None
        self._tools = []

    def tools(self) -> list[MCPToolProxy]:
        return list(self._tools)

    def status_summary(self) -> str:
        names = ", ".join(server.name for server in self.registry.all())
        if not names:
            return ""
        count = len(self._tools)
        noun = "tool" if count == 1 else "tools"
        return f"MCP connected: {names} ({count} {noun} available)"


def _nearest_project_config(start: Path) -> Path | None:
    if start.is_file():
        start = start.parent
    for base in [start, *start.parents]:
        candidate = base / ".mcp.json"
        if candidate.is_file():
            return candidate
    return None


def _parse_server(
    config_path: Path,
    name: object,
    config: object,
    env: Mapping[str, str],
) -> MCPServer:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{config_path}: MCP server names must be non-empty strings")
    if not isinstance(config, dict):
        raise ValueError(f"{config_path}: MCP server '{name}' must be a JSON object")

    expanded = _expand_value(config, env)
    if not isinstance(expanded, dict):
        raise ValueError(f"{config_path}: MCP server '{name}' must be a JSON object")

    transport = expanded.get("type")
    if transport is None and "command" in expanded:
        transport = "stdio"
    if not isinstance(transport, str) or transport not in _KNOWN_TRANSPORTS:
        raise ValueError(
            f"{config_path}: MCP server '{name}' has invalid transport {transport!r}"
        )

    command = _optional_string(config_path, name, expanded.get("command"), "command")
    args = _string_list(config_path, name, expanded.get("args"), "args")
    server_env = _string_mapping(config_path, name, expanded.get("env"), "env")
    url = _optional_string(config_path, name, expanded.get("url"), "url")
    headers = _optional_string_mapping(config_path, name, expanded.get("headers"), "headers")
    oauth = _optional_mapping(config_path, name, expanded.get("oauth"), "oauth")
    headers_helper = _optional_string(
        config_path,
        name,
        expanded.get("headersHelper"),
        "headersHelper",
    )

    if transport == "stdio" and command is None:
        raise ValueError(f"{config_path}: MCP server '{name}' requires 'command' for stdio")
    if transport in {"http", "sse"} and url is None:
        raise ValueError(f"{config_path}: MCP server '{name}' requires 'url' for {transport}")

    metadata = {
        key: value
        for key, value in expanded.items()
        if key
        not in {"type", "command", "args", "env", "url", "headers", "oauth", "headersHelper"}
    }

    return MCPServer(
        name=name.strip(),
        config_path=config_path,
        transport=transport,
        command=command,
        args=args,
        env=server_env,
        url=url,
        headers=headers,
        oauth=oauth,
        headers_helper=headers_helper,
        metadata=metadata or None,
    )


def _expand_value(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _expand_string(value, env)
    if isinstance(value, list):
        return [_expand_value(item, env) for item in value]
    if isinstance(value, dict):
        return {key: _expand_value(item, env) for key, item in value.items()}
    return value


def _expand_string(text: str, env: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        if name in env:
            return env[name]
        if default is not None:
            return default
        raise ValueError(f"missing environment variable '{name}'")

    return _ENV_VAR_RE.sub(replace, text)


def _optional_string(
    config_path: Path,
    name: str,
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{config_path}: MCP server '{name}' field '{field_name}' must be a string")
    return value


def _string_list(
    config_path: Path,
    name: str,
    value: object,
    field_name: str,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"{config_path}: MCP server '{name}' field '{field_name}' must be a list of strings"
        )
    return list(value)


def _optional_mapping(
    config_path: Path,
    name: str,
    value: object,
    field_name: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{config_path}: MCP server '{name}' field '{field_name}' must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(
            f"{config_path}: MCP server '{name}' field '{field_name}' must use string keys"
        )
    return dict(value)


def _string_mapping(
    config_path: Path,
    name: str,
    value: object,
    field_name: str,
) -> dict[str, str]:
    mapping = _optional_string_mapping(config_path, name, value, field_name)
    return mapping or {}


def _optional_string_mapping(
    config_path: Path,
    name: str,
    value: object,
    field_name: str,
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{config_path}: MCP server '{name}' field '{field_name}' must be an object")

    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(
                f"{config_path}: MCP server '{name}' field '{field_name}' must map strings to strings"
            )
        result[key] = item
    return result


def _tool_definition_from_mcp(tool: Any) -> ToolDefinition:
    name = getattr(tool, "name")
    description = getattr(tool, "description", "") or ""
    schema = getattr(tool, "inputSchema", None)
    if schema is None:
        schema = getattr(tool, "input_schema", None)
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}, "required": []}
    else:
        schema = {
            "type": schema.get("type", "object"),
            "properties": dict(schema.get("properties", {})),
            "required": list(schema.get("required", [])),
        }
    return ToolDefinition(name=name, description=description, parameters=schema)


def _stringify_tool_result(result: Any) -> str:
    data = getattr(result, "data", None)
    if isinstance(data, str):
        return data
    if data is not None:
        try:
            return json.dumps(data, ensure_ascii=True, default=str)
        except TypeError:
            return str(data)

    content = getattr(result, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            else:
                parts.append(str(item))
        if parts:
            return "\n".join(parts)
    return ""
