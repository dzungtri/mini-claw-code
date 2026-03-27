import asyncio
from collections import deque
import json
from pathlib import Path
import sys

import pytest

from mini_claw_code_py import (
    AgentNotice,
    Message,
    MCPRegistry,
    MockStreamProvider,
    PlanAgent,
    StopReason,
    ToolCall,
    default_mcp_config_paths,
    parse_mcp_config,
)
from mini_claw_code_py.types import AssistantTurn


def _write_mcp_config(path: Path, servers: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8")
    return path


def test_ch15_parse_sample_mcp_config() -> None:
    config_path = Path(__file__).resolve().parents[1] / ".mcp.json"

    servers = parse_mcp_config(config_path, env={})

    assert [server.name for server in servers] == [
        "filesystem-demo",
        "langchain-docs",
    ]
    docs = next(server for server in servers if server.name == "langchain-docs")
    fs = next(server for server in servers if server.name == "filesystem-demo")

    assert docs.transport == "http"
    assert docs.url == "https://docs.langchain.com/mcp"
    assert docs.headers is None
    assert fs.transport == "stdio"
    assert fs.command == "npx"
    assert fs.args == ["-y", "@modelcontextprotocol/server-filesystem", "."]
    assert fs.env == {}


def test_ch15_defaults_missing_type_to_stdio(tmp_path: Path) -> None:
    config_path = _write_mcp_config(
        tmp_path / ".mcp.json",
        {
            "local-tools": {
                "command": "python",
                "args": ["server.py"],
                "env": {},
            }
        },
    )

    [server] = parse_mcp_config(config_path, env={})

    assert server.name == "local-tools"
    assert server.transport == "stdio"
    assert server.command == "python"


def test_ch15_expands_required_and_default_env_values(tmp_path: Path) -> None:
    config_path = _write_mcp_config(
        tmp_path / ".mcp.json",
        {
            "api-server": {
                "type": "http",
                "url": "${API_BASE_URL:-https://api.example.com}/mcp",
                "headers": {
                    "Authorization": "Bearer ${API_KEY}",
                },
            }
        },
    )

    [server] = parse_mcp_config(config_path, env={"API_KEY": "secret-token"})

    assert server.url == "https://api.example.com/mcp"
    assert server.headers == {"Authorization": "Bearer secret-token"}


def test_ch15_rejects_missing_required_env_value(tmp_path: Path) -> None:
    config_path = _write_mcp_config(
        tmp_path / ".mcp.json",
        {
            "api-server": {
                "type": "http",
                "url": "https://api.example.com/mcp",
                "headers": {
                    "Authorization": "Bearer ${API_KEY}",
                },
            }
        },
    )

    with pytest.raises(ValueError, match="missing environment variable 'API_KEY'"):
        parse_mcp_config(config_path, env={})


def test_ch15_project_config_overrides_user_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "workspace" / "demo"

    _write_mcp_config(
        home / ".mcp.json",
        {
            "docs-api": {
                "type": "http",
                "url": "https://user.example.com/mcp",
            }
        },
    )
    _write_mcp_config(
        project / ".mcp.json",
        {
            "docs-api": {
                "type": "http",
                "url": "https://project.example.com/mcp",
            }
        },
    )

    registry = MCPRegistry.discover(default_mcp_config_paths(cwd=project, home=home), env={})
    server = registry.get("docs-api")

    assert server is not None
    assert server.url == "https://project.example.com/mcp"
    assert server.config_path == project / ".mcp.json"


def test_ch15_prompt_section_lists_server_details(tmp_path: Path) -> None:
    config_path = _write_mcp_config(
        tmp_path / ".mcp.json",
        {
            "internal-api": {
                "type": "http",
                "url": "https://internal.example.com/mcp",
                "headersHelper": "/opt/bin/get-mcp-headers.sh",
            }
        },
    )

    registry = MCPRegistry.discover([config_path], env={})
    section = registry.prompt_section()

    assert "<mcp_system>" in section
    assert "<configured_mcp_servers>" in section
    assert "<name>internal-api</name>" in section
    assert "<transport>http</transport>" in section
    assert f"<source>{config_path}</source>" in section
    assert "Do not invent MCP tools" in section
    assert "HTTP MCP server at https://internal.example.com/mcp" in section


def test_ch15_plan_agent_can_append_default_mcp_prompt(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "workspace" / "demo"
    project.mkdir(parents=True)
    _write_mcp_config(
        project / ".mcp.json",
        {
            "docs-api": {
                "type": "http",
                "url": "https://project.example.com/mcp",
            }
        },
    )

    agent = PlanAgent(MockStreamProvider(deque())).enable_default_mcp(
        cwd=project,
        home=home,
        env={},
    )

    assert "<mcp_system>" in agent.execution_system_prompt
    assert "<name>docs-api</name>" in agent.execution_system_prompt
    assert "<mcp_system>" in agent.plan_system_prompt


@pytest.mark.asyncio
async def test_ch15_plan_agent_can_call_mcp_tool_from_config(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    project.mkdir(parents=True)
    server_script = project / "demo_mcp_server.py"
    server_script.write_text(
        """import asyncio

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


app = Server("Demo Server")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="greet",
            description="Return a greeting.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, object]) -> list[types.TextContent]:
    if name != "greet":
        raise ValueError(f"unknown tool: {name}")
    person = str(arguments.get("name", ""))
    return [types.TextContent(type="text", text=f"Hello, {person}!")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
""",
        encoding="utf-8",
    )

    _write_mcp_config(
        project / ".mcp.json",
        {
            "demo": {
                "command": sys.executable,
                "args": [str(server_script)],
                "env": {},
            }
        },
    )

    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(id="c1", name="greet", arguments={"name": "Ada"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Finished with MCP.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = PlanAgent(provider).enable_default_mcp(cwd=project, env={})
    events: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Use MCP to greet Ada")]

    result = await agent.execute(messages, events)

    assert result == "Finished with MCP."
    assert any(
        message.kind == "tool_result" and message.content == "Hello, Ada!"
        for message in messages
    )
    seen_notice = False
    while not events.empty():
        event = await events.get()
        if isinstance(event, AgentNotice):
            seen_notice = True
            assert "MCP connected: demo" in event.message
            assert "tool available" in event.message
    assert seen_notice
