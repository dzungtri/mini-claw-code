from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class MemorySource:
    scope: str
    path: Path


@dataclass(slots=True)
class MemoryDocument:
    scope: str
    path: Path
    content: str


def default_memory_sources(
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[MemorySource]:
    start = (cwd or Path.cwd()).resolve()
    user_home = (home or Path.home()).expanduser().resolve()

    sources: list[MemorySource] = []
    project_memory = _nearest_project_memory_file(start)
    if project_memory is not None:
        sources.append(MemorySource(scope="project", path=project_memory))

    user_memory = user_home / ".agents" / "AGENTS.md"
    if user_memory.is_file():
        sources.append(MemorySource(scope="user", path=user_memory))
    return sources


def load_memory_sources(sources: Iterable[MemorySource]) -> list[MemoryDocument]:
    documents: list[MemoryDocument] = []
    for source in sources:
        if not source.path.is_file():
            continue
        content = source.path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        documents.append(
            MemoryDocument(
                scope=source.scope,
                path=source.path,
                content=content,
            )
        )
    return documents


def render_memory_prompt_section(documents: list[MemoryDocument]) -> str:
    if not documents:
        return ""

    blocks: list[str] = [
        "<agent_memory>",
        "The runtime loaded durable memory from local AGENTS.md files.",
        "Treat this as stable guidance that may apply across tasks.",
        "Do not treat memory as current-task scratch space.",
        "",
    ]

    for document in documents:
        blocks.append(f'<memory scope="{document.scope}" path="{document.path}">')
        blocks.extend(document.content.splitlines())
        blocks.append("</memory>")
        blocks.append("")

    blocks.append("</agent_memory>")
    return "\n".join(blocks)


class MemoryRegistry:
    def __init__(self, sources: list[MemorySource] | None = None) -> None:
        self._sources = sources or []

    @classmethod
    def discover(
        cls,
        sources: Iterable[MemorySource],
    ) -> "MemoryRegistry":
        registry = cls()
        for source in sources:
            registry.add(source.scope, source.path)
        return registry

    @classmethod
    def discover_default(
        cls,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "MemoryRegistry":
        return cls.discover(default_memory_sources(cwd=cwd, home=home))

    def add(
        self,
        scope: str,
        path: str | Path,
    ) -> None:
        source = MemorySource(scope=scope, path=_resolve_memory_path(path))
        self._sources = [
            existing
            for existing in self._sources
            if not (existing.scope == source.scope and existing.path == source.path)
        ]
        self._sources.append(source)

    def extend(self, sources: Iterable[MemorySource]) -> None:
        for source in sources:
            self.add(source.scope, source.path)

    def all(self) -> list[MemorySource]:
        return list(self._sources)

    def load(self) -> list[MemoryDocument]:
        return load_memory_sources(self._sources)

    def prompt_section(self) -> str:
        return render_memory_prompt_section(self.load())

    def status_summary(self) -> str:
        documents = self.load()
        if not documents:
            return ""
        count = len(documents)
        noun = "file" if count == 1 else "files"
        labels = ", ".join(f"{document.scope} ({document.path})" for document in documents)
        return f"Memory loaded: {count} {noun} [{labels}]"


def _nearest_project_memory_file(start: Path) -> Path | None:
    if start.is_file():
        start = start.parent
    for base in [start, *start.parents]:
        candidate = base / ".agents" / "AGENTS.md"
        if candidate.is_file():
            return candidate
    return None


def _resolve_memory_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()
