import asyncio
from collections import deque
from pathlib import Path
import sys

import pytest

from mini_claw_code_py import (
    HarnessAgent,
    MCPCatalog,
    MCPRegistry,
    MCPToolAdapter,
    Message,
    MockStreamProvider,
    PlanAgent,
    StopReason,
    ToolCall,
)
from mini_claw_code_py.types import AssistantTurn


def _write_mcp_server(path: Path) -> Path:
    path.write_text(
        """import asyncio

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


app = Server("Demo MCP")


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


@app.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            name="guide",
            uri="file:///guide.txt",
            description="Project guide",
            mimeType="text/plain",
        )
    ]


@app.read_resource()
async def read_resource(uri) -> str:
    if str(uri) != "file:///guide.txt":
        raise ValueError(f"unknown resource: {uri}")
    return "Guide body"


@app.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="review_template",
            description="Review template",
            arguments=[
                types.PromptArgument(
                    name="topic",
                    description="Review topic",
                    required=False,
                )
            ],
        )
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    if name != "review_template":
        raise ValueError(f"unknown prompt: {name}")
    topic = (arguments or {}).get("topic", "general")
    return types.GetPromptResult(
        description="Prompt ready",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=f"Review {topic} carefully."),
            )
        ],
    )


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
""",
        encoding="utf-8",
    )
    return path


def _write_mcp_config(path: Path, *, server_script: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "{\n"
            '  "mcpServers": {\n'
            '    "demo": {\n'
            f'      "command": "{sys.executable}",\n'
            f'      "args": ["{server_script}"],\n'
            '      "env": {}\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_ch34_mcp_catalog_renders_resources_and_prompts() -> None:
    catalog = MCPCatalog()
    catalog.replace(
        servers=["demo"],
        tool_count=3,
        resources=[],
        prompts=[],
    )

    assert "MCP connected: demo (3 tools available, 0 resources available, 0 prompts available)" == catalog.status_summary()
    assert "Resources: none" in catalog.render()
    assert "Prompts: none" in catalog.render()


def test_ch34_registry_render_shows_configured_status(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    project.mkdir(parents=True)
    server_script = _write_mcp_server(project / "demo_mcp_server.py")
    config_path = _write_mcp_config(project / ".mcp.json", server_script=server_script)
    registry = MCPRegistry.discover([config_path], env={})

    rendered = registry.render()

    assert "Configured MCP servers:" in rendered
    assert "- demo [stdio] (configured)" in rendered
    assert str(config_path) in rendered


@pytest.mark.asyncio
async def test_ch34_mcp_adapter_exposes_resource_and_prompt_tools(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    project.mkdir(parents=True)
    server_script = _write_mcp_server(project / "demo_mcp_server.py")
    config_path = _write_mcp_config(project / ".mcp.json", server_script=server_script)
    registry = MCPRegistry.discover([config_path], env={})

    async with MCPToolAdapter(registry) as adapter:
        names = [tool.definition.name for tool in adapter.tools()]
        assert "greet" in names
        assert "mcp_read_resource" in names
        assert "mcp_get_prompt" in names
        assert "1 resource" in adapter.status_summary()
        assert "1 prompt" in adapter.status_summary()

        resource_tool = next(tool for tool in adapter.tools() if tool.definition.name == "mcp_read_resource")
        prompt_tool = next(tool for tool in adapter.tools() if tool.definition.name == "mcp_get_prompt")
        guide = await resource_tool.call({"server": "demo", "uri": "file:///guide.txt"})
        prompt = await prompt_tool.call(
            {"server": "demo", "name": "review_template", "arguments": {"topic": "parser"}}
        )

        assert guide == "Guide body"
        assert "Prompt ready" in prompt
        assert "[user] Review parser carefully." in prompt
        runtime_section = adapter.runtime_prompt_section()
        assert "<mcp_runtime>" in runtime_section
        assert "file:///guide.txt" in runtime_section
        assert "review_template" in runtime_section


@pytest.mark.asyncio
async def test_ch34_plan_agent_can_call_mcp_resource_and_prompt_tools(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    project.mkdir(parents=True)
    server_script = _write_mcp_server(project / "demo_mcp_server.py")
    _write_mcp_config(project / ".mcp.json", server_script=server_script)
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="mcp_read_resource",
                            arguments={"server": "demo", "uri": "file:///guide.txt"},
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c2",
                            name="mcp_get_prompt",
                            arguments={
                                "server": "demo",
                                "name": "review_template",
                                "arguments": {"topic": "parser"},
                            },
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Finished.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = PlanAgent(provider).enable_default_mcp(cwd=project, env={})
    events: asyncio.Queue[object] = asyncio.Queue()
    messages = [Message.user("Use MCP resource and prompt surfaces.")]

    result = await agent.execute(messages, events)

    assert result == "Finished."
    tool_results = [message.content for message in messages if message.kind == "tool_result"]
    assert "Guide body" in tool_results
    assert any(result and "Review parser carefully." in result for result in tool_results)
    assert messages[0].kind == "system"
    assert messages[0].content is not None
    assert "<mcp_runtime>" in messages[0].content


@pytest.mark.asyncio
async def test_ch34_harness_tracks_connected_mcp_catalog(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    project.mkdir(parents=True)
    server_script = _write_mcp_server(project / "demo_mcp_server.py")
    _write_mcp_config(project / ".mcp.json", server_script=server_script)
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = HarnessAgent(provider).enable_default_mcp(cwd=project, env={})
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("Show MCP state.")], queue)

    rendered = agent.mcp_status_text()
    assert "MCP connected: demo" in rendered
    assert "- demo [stdio] (connected)" in rendered
    assert "file:///guide.txt" in rendered
    assert "review_template" in rendered


def test_ch34_harness_mcp_status_text_shows_configured_servers_before_first_turn(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    project.mkdir(parents=True)
    server_script = _write_mcp_server(project / "demo_mcp_server.py")
    _write_mcp_config(project / ".mcp.json", server_script=server_script)
    agent = HarnessAgent(MockStreamProvider(deque())).enable_default_mcp(cwd=project, env={})

    rendered = agent.mcp_status_text()

    assert "Configured MCP servers:" in rendered
    assert "- demo [stdio] (configured)" in rendered
    assert "Live MCP catalog: not connected in this session yet." in rendered
