from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import ToolDefinition, ToolSet


TOOL_UNIVERSE_PROMPT_SECTION = """<tool_universe_system>
You are running with tool-universe management enabled.

Bundled core tools stay visible by default.
Some external tools may be deferred to keep the active tool schema set small.

Use `tool_search` when:
- bundled tools are not enough for the task
- you need an external integration or domain-specific capability
- you suspect MCP tools may provide the needed operation

Deferred-tool workflow:
1. Search with capability words such as `docs`, `database`, `git`, `filesystem`, or `search`.
2. Read the matched tool names and descriptions.
3. Activate the relevant tools with `tool_search(query="select:name1,name2")`.
4. Call the activated tools directly in the next turn.

Use deferred tools proactively when they are clearly a better fit than bundled tools, but keep the active external set narrow and task-relevant.
</tool_universe_system>"""


@dataclass(slots=True)
class DeferredToolEntry:
    name: str
    description: str
    source: str
    tool: object


class DeferredToolRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, DeferredToolEntry] = {}

    def register(self, tool: object, *, source: str) -> None:
        definition = getattr(tool, "definition", None)
        if definition is None:
            raise ValueError("deferred tool must expose a definition")
        self._entries[definition.name] = DeferredToolEntry(
            name=definition.name,
            description=definition.description,
            source=source,
            tool=tool,
        )

    def all(self) -> list[DeferredToolEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.name)

    def search(self, query: str, *, limit: int = 5) -> list[DeferredToolEntry]:
        query_text = query.strip()
        if not query_text:
            return self.all()[:limit]

        lowered = query_text.casefold()
        scored: list[tuple[int, DeferredToolEntry]] = []
        for entry in self._entries.values():
            haystack = f"{entry.name} {entry.description} {entry.source}".casefold()
            if lowered not in haystack:
                continue
            score = 2 if lowered in entry.name.casefold() else 1
            scored.append((score, entry))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [entry for _, entry in scored[:limit]]

    def select(self, names: list[str]) -> list[DeferredToolEntry]:
        selected: list[DeferredToolEntry] = []
        for name in names:
            entry = self._entries.get(name)
            if entry is not None:
                selected.append(entry)
        return selected

    def count(self) -> int:
        return len(self._entries)

    def names(self, *, limit: int = 12) -> list[str]:
        return [entry.name for entry in self.all()[:limit]]


class ToolSearchTool:
    def __init__(
        self,
        registry: DeferredToolRegistry,
        runtime_tools: ToolSet,
    ) -> None:
        self._registry = registry
        self._runtime_tools = runtime_tools
        self._definition = ToolDefinition.new(
            "tool_search",
            "Search deferred external tools and activate the relevant ones for the current run.",
        ).param(
            "query",
            "string",
            'Search text such as "docs" or an activation request like "select:tool_name".',
            True,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        query = args.get("query") if isinstance(args, dict) else None
        if not isinstance(query, str) or not query.strip():
            raise ValueError("missing required parameter: query")

        query = query.strip()
        if query.startswith("select:"):
            names = [name.strip() for name in query[7:].split(",") if name.strip()]
            selected = self._registry.select(names)
            if not selected:
                return f"No deferred tools matched activation request: {query}"
            for entry in selected:
                self._runtime_tools.push(entry.tool)  # type: ignore[arg-type]
            lines = ["Activated deferred tools for this run:"]
            for entry in selected:
                lines.append(f"- {entry.name} [{entry.source}]")
            lines.append("You can now call these tools directly.")
            return "\n".join(lines)

        matches = self._registry.search(query)
        if not matches:
            return f"No deferred tools matched: {query}"

        lines = ["Deferred tools that match your query:"]
        for entry in matches:
            lines.append(f"- {entry.name} [{entry.source}]: {entry.description or 'No description.'}")
        names = ",".join(entry.name for entry in matches)
        lines.append(f'Activate tools with: tool_search(query="select:{names}")')
        return "\n".join(lines)


def render_tool_universe_prompt_section() -> str:
    return TOOL_UNIVERSE_PROMPT_SECTION


def tool_universe_status_summary(
    *,
    built_in_count: int,
    skill_count: int,
    deferred_count: int,
) -> str:
    parts = [f"{built_in_count} bundled tool(s)"]
    if skill_count:
        parts.append(f"{skill_count} skill(s)")
    if deferred_count:
        parts.append(f"{deferred_count} deferred external tool(s)")
    return "Tool universe ready: " + ", ".join(parts)
