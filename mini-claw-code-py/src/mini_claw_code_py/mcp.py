from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters, types as mcp_types
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from .types import JSONValue, ToolDefinition


_ENV_VAR_RE = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_KNOWN_TRANSPORTS = {"stdio", "http", "sse"}
_STDIO_ERRLOG = open(os.devnull, "w", encoding="utf-8")


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
    def __init__(self, session: ClientSession, definition: ToolDefinition) -> None:
        self._session = session
        self._definition = definition

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: JSONValue) -> str:
        arguments = args if isinstance(args, dict) else {}
        result = await self._session.call_tool(self._definition.name, arguments)
        return _stringify_tool_result(result)


class MCPToolAdapter:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._stack: AsyncExitStack | None = None
        self._tools: list[MCPToolProxy] = []

    async def __aenter__(self) -> "MCPToolAdapter":
        if not self.registry.all():
            return self

        stack = AsyncExitStack()
        await stack.__aenter__()

        try:
            for server in self.registry.all():
                session = await _open_mcp_session(stack, server)
                for tool in await _list_all_tools(session):
                    self._tools.append(MCPToolProxy(session, _tool_definition_from_mcp(tool)))
        except BaseException as exc:
            await stack.__aexit__(type(exc), exc, exc.__traceback__)
            raise

        self._stack = stack
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, tb)
            self._stack = None
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


async def _open_mcp_session(stack: AsyncExitStack, server: MCPServer) -> ClientSession:
    read_stream, write_stream = await _open_transport(stack, server)
    session = ClientSession(read_stream, write_stream)
    await stack.enter_async_context(session)
    await session.initialize()
    return session


async def _list_all_tools(session: ClientSession) -> list[mcp_types.Tool]:
    tools: list[mcp_types.Tool] = []
    cursor: str | None = None
    while True:
        result = await session.list_tools(cursor=cursor)
        tools.extend(result.tools)
        cursor = result.nextCursor
        if cursor is None:
            return tools


@asynccontextmanager
async def _server_transport(
    server: MCPServer,
) -> AsyncIterator[tuple[Any, Any]]:
    params = _build_server_params(server)

    if server.transport == "stdio":
        async with stdio_client(
            StdioServerParameters(
                command=params["command"],
                args=params["args"],
                env=params.get("env"),
                cwd=params["cwd"],
            ),
            errlog=_STDIO_ERRLOG,
        ) as streams:
            yield streams
        return

    if server.transport == "http":
        async with httpx.AsyncClient(
            headers=params.get("headers"),
            timeout=httpx.Timeout(30.0, read=300.0),
        ) as client:
            async with streamable_http_client(params["url"], http_client=client) as streams:
                read_stream, write_stream, _session_id = streams
                yield read_stream, write_stream
        return

    if server.transport == "sse":
        async with sse_client(params["url"], headers=params.get("headers")) as streams:
            yield streams
        return

    raise ValueError(f"unsupported transport: {server.transport}")


async def _open_transport(
    stack: AsyncExitStack,
    server: MCPServer,
) -> tuple[Any, Any]:
    read_stream, write_stream = await stack.enter_async_context(_server_transport(server))
    return read_stream, write_stream


def _build_server_params(server: MCPServer) -> dict[str, Any]:
    params: dict[str, Any] = {"transport": server.transport}

    if server.transport == "stdio":
        if server.command is None:
            raise ValueError(f"MCP server '{server.name}' requires 'command' for stdio")
        params["command"] = server.command
        params["args"] = list(server.args)
        if server.env:
            params["env"] = dict(server.env)
        params["cwd"] = server.config_path.parent
        return params

    if server.transport in {"http", "sse"}:
        if server.url is None:
            raise ValueError(f"MCP server '{server.name}' requires 'url' for {server.transport}")
        params["url"] = server.url
        if server.headers:
            params["headers"] = dict(server.headers)
        return params

    raise ValueError(f"MCP server '{server.name}' has unsupported transport: {server.transport}")


def _tool_definition_from_mcp(tool: mcp_types.Tool) -> ToolDefinition:
    description = tool.description or ""
    schema = tool.inputSchema
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}, "required": []}
    else:
        schema = {
            "type": schema.get("type", "object"),
            "properties": dict(schema.get("properties", {})),
            "required": list(schema.get("required", [])),
        }
    return ToolDefinition(name=tool.name, description=description, parameters=schema)


def _stringify_tool_result(result: mcp_types.CallToolResult) -> str:
    rendered = _render_content_blocks(result.content)
    if rendered:
        return f"error: {rendered}" if result.isError else rendered

    if result.structuredContent is not None:
        try:
            rendered = json.dumps(result.structuredContent, ensure_ascii=True, default=str)
        except TypeError:
            rendered = str(result.structuredContent)
        return f"error: {rendered}" if result.isError else rendered

    if result.isError:
        return "error: MCP tool call failed"
    return ""


def _render_content_blocks(content: list[mcp_types.ContentBlock]) -> str:
    parts: list[str] = []
    for item in content:
        text = _render_content_block(item)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _render_content_block(item: mcp_types.ContentBlock) -> str:
    if isinstance(item, mcp_types.TextContent):
        return item.text
    if isinstance(item, mcp_types.ImageContent):
        return f"[image {item.mimeType}, {len(item.data)} bytes]"
    if isinstance(item, mcp_types.EmbeddedResource):
        resource = item.resource
        if isinstance(resource, mcp_types.TextResourceContents):
            return resource.text
        if isinstance(resource, mcp_types.BlobResourceContents):
            mime = resource.mimeType or "application/octet-stream"
            return f"[resource blob {mime}, {len(resource.blob)} bytes]"

    if hasattr(item, "model_dump"):
        try:
            return json.dumps(item.model_dump(mode="json"), ensure_ascii=True, default=str)
        except TypeError:
            return str(item)
    return str(item)
