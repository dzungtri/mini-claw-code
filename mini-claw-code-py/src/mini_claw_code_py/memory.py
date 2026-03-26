from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Sequence

from .types import AssistantTurn, Message, Provider, StopReason


LEARNED_MEMORY_START = "<!-- mini-claw:memory-updater:start -->"
LEARNED_MEMORY_END = "<!-- mini-claw:memory-updater:end -->"

_LEARNED_MEMORY_RE = re.compile(
    re.escape(LEARNED_MEMORY_START) + r"\n?(.*?)\n?" + re.escape(LEARNED_MEMORY_END),
    re.DOTALL,
)
_MEMORY_SIGNAL_RE = re.compile(
    r"\b("
    r"remember|prefer|always|never|avoid|use\b|for future|next time|by default|"
    r"keep\b|please\b|should\b|must\b|don't\b|do not\b|in this project|for this repo|"
    r"concise|verbose|short|detailed"
    r")\b",
    re.IGNORECASE,
)

MEMORY_UPDATE_PROMPT = """You maintain durable agent memory in an AGENTS.md file.

Current memory scope: {scope}
Current AGENTS.md contents:
<current_memory>
{current_memory}
</current_memory>

Recent meaningful conversation:
<conversation>
{conversation}
</conversation>

Decide whether this conversation contains durable, reusable, safe guidance worth remembering.

Remember:
- Prefer stable user preferences, workflow rules, repository conventions, and reusable commands.
- Do not store one-off requests, temporary task state, raw tool output, or secrets.
- Keep memory lines short and general.
- Return at most 3 lines.

Return strict JSON with this shape:
{{
  "should_write": true,
  "lines": [
    "Use `uv run pytest` for Python tests.",
    "Prefer concise final answers."
  ]
}}
"""


@dataclass(slots=True)
class MemorySource:
    scope: str
    path: Path


@dataclass(slots=True)
class MemoryDocument:
    scope: str
    path: Path
    content: str


@dataclass(slots=True)
class MemoryUpdateRequest:
    source: MemorySource
    messages: list[Message]


MemoryNoticeCallback = Callable[[str], Awaitable[None] | None]


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


def filter_messages_for_memory(messages: Sequence[Message]) -> list[Message]:
    filtered: list[Message] = []
    for message in messages:
        if message.kind == "user" and message.content:
            filtered.append(Message.user(message.content))
            continue

        if message.kind != "assistant" or message.turn is None:
            continue

        turn = message.turn
        if turn.tool_calls:
            continue
        if not turn.text:
            continue

        filtered.append(
            Message.assistant(
                AssistantTurn(
                    text=turn.text,
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            )
        )
    return filtered


def select_recent_memory_messages(
    messages: Sequence[Message],
    *,
    max_messages: int = 6,
) -> list[Message]:
    filtered = filter_messages_for_memory(messages)
    if max_messages < 1:
        return filtered
    return filtered[-max_messages:]


def latest_memory_exchange(messages: Sequence[Message]) -> list[Message]:
    filtered = filter_messages_for_memory(messages)
    if len(filtered) < 2:
        return filtered

    tail = filtered[-2:]
    if tail[0].kind == "user" and tail[1].kind == "assistant":
        return tail
    return filtered[-1:]


def should_consider_memory_update(messages: Sequence[Message]) -> bool:
    filtered = filter_messages_for_memory(messages)
    if len(filtered) < 2:
        return False

    user_text = "\n".join(message.content or "" for message in filtered if message.kind == "user")
    return bool(_MEMORY_SIGNAL_RE.search(user_text))


def extract_learned_memory_lines(text: str) -> list[str]:
    match = _LEARNED_MEMORY_RE.search(text)
    if not match:
        return []
    lines = []
    for raw_line in match.group(1).splitlines():
        normalized = _normalize_memory_line(raw_line)
        if normalized:
            lines.append(normalized)
    return lines


def merge_learned_memory_lines(
    text: str,
    new_lines: Sequence[str],
) -> str:
    normalized_new = [
        normalized
        for normalized in (_normalize_memory_line(line) for line in new_lines)
        if normalized
    ]
    if not normalized_new:
        return text

    existing_lines = extract_learned_memory_lines(text)
    merged_lines = _dedupe_memory_lines([*existing_lines, *normalized_new])
    block = _render_learned_memory_block(merged_lines)

    if _LEARNED_MEMORY_RE.search(text):
        updated = _LEARNED_MEMORY_RE.sub(block, text, count=1)
        return updated.rstrip() + "\n"

    stripped = text.rstrip()
    if stripped:
        return f"{stripped}\n\n{block}\n"
    return f"{block}\n"


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

    def get(self, scope: str) -> MemorySource | None:
        for source in reversed(self._sources):
            if source.scope == scope:
                return source
        return None

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


class MemoryUpdater:
    def __init__(
        self,
        provider: Provider,
        *,
        max_messages: int = 6,
    ) -> None:
        self.provider = provider
        self.max_messages = max_messages

    async def suggest_lines(
        self,
        source: MemorySource,
        messages: Sequence[Message],
    ) -> list[str]:
        recent_messages = select_recent_memory_messages(messages, max_messages=self.max_messages)
        if not should_consider_memory_update(recent_messages):
            return []

        current_memory = ""
        if source.path.is_file():
            current_memory = source.path.read_text(encoding="utf-8").strip()
        if not current_memory:
            current_memory = "(empty)"

        prompt = MEMORY_UPDATE_PROMPT.format(
            scope=source.scope,
            current_memory=current_memory,
            conversation=_format_memory_conversation(recent_messages),
        )
        turn = await self.provider.chat(
            [Message.user(prompt)],
            [],
        )
        return _parse_memory_update_lines(turn.text)

    async def update(
        self,
        source: MemorySource,
        messages: Sequence[Message],
    ) -> int:
        lines = await self.suggest_lines(source, messages)
        if not lines:
            return 0
        return update_memory_file(source.path, lines)


class MemoryUpdateQueue:
    def __init__(
        self,
        updater: MemoryUpdater,
        *,
        debounce_seconds: float = 2.0,
        on_notice: MemoryNoticeCallback | None = None,
    ) -> None:
        self.updater = updater
        self.debounce_seconds = debounce_seconds
        self.on_notice = on_notice
        self._pending: dict[tuple[str, Path], MemoryUpdateRequest] = {}
        self._debounce_task: asyncio.Task[None] | None = None
        self._processing = False

    async def add(
        self,
        source: MemorySource,
        messages: Sequence[Message],
    ) -> None:
        request = MemoryUpdateRequest(
            source=source,
            messages=list(messages),
        )
        self._pending[(source.scope, source.path)] = request
        self._schedule()

    async def flush(self) -> None:
        if self._debounce_task is not None:
            self._debounce_task.cancel()
            self._debounce_task = None
        await self._process_pending()

    def _schedule(self) -> None:
        if self._debounce_task is not None:
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._debounced_process())

    async def _debounced_process(self) -> None:
        try:
            if self.debounce_seconds > 0:
                await asyncio.sleep(self.debounce_seconds)
            await self._process_pending()
        except asyncio.CancelledError:
            return

    async def _process_pending(self) -> None:
        if self._processing or not self._pending:
            return

        self._processing = True
        pending = list(self._pending.values())
        self._pending.clear()
        try:
            for request in pending:
                try:
                    added = await self.updater.update(request.source, request.messages)
                except Exception as exc:
                    await self._emit_notice(
                        f"Memory update failed for {request.source.scope} memory: {exc}"
                    )
                    continue
                if added > 0:
                    noun = "line" if added == 1 else "lines"
                    await self._emit_notice(
                        f"Memory updated: {request.source.scope} memory (+{added} {noun})."
                    )
        finally:
            self._processing = False
            if self._pending:
                self._schedule()

    async def _emit_notice(self, message: str) -> None:
        if self.on_notice is None:
            return
        result = self.on_notice(message)
        if result is not None:
            await result


def update_memory_file(
    path: Path,
    new_lines: Sequence[str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
    before = extract_learned_memory_lines(existing)
    updated = merge_learned_memory_lines(existing, new_lines)
    path.write_text(updated, encoding="utf-8")
    after = extract_learned_memory_lines(updated)
    return max(0, len(after) - len(before))


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


def _normalize_memory_line(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("- "):
        normalized = normalized[2:].strip()
    elif normalized.startswith("* "):
        normalized = normalized[2:].strip()
    return normalized


def _render_learned_memory_block(lines: Sequence[str]) -> str:
    body = "\n".join(f"- {line}" for line in lines)
    return "\n".join(
        [
            LEARNED_MEMORY_START,
            body,
            LEARNED_MEMORY_END,
        ]
    )


def _dedupe_memory_lines(lines: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    for line in lines:
        key = _memory_line_key(line)
        replaced = False

        for index, existing in enumerate(deduped):
            existing_key = _memory_line_key(existing)
            if key == existing_key:
                replaced = True
                break
            if key in existing_key:
                replaced = True
                break
            if existing_key in key:
                deduped[index] = line
                replaced = True
                break

        if not replaced:
            deduped.append(line)
    return deduped


def _memory_line_key(line: str) -> str:
    normalized = line.strip().lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _format_memory_conversation(messages: Sequence[Message]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.kind == "user" and message.content:
            lines.append(f"User: {message.content}")
        elif message.kind == "assistant" and message.turn is not None and message.turn.text:
            lines.append(f"Assistant: {message.turn.text}")
    return "\n".join(lines)


def _parse_memory_update_lines(text: str | None) -> list[str]:
    if not text:
        return []
    raw_text = text.strip()
    if raw_text.startswith("```"):
        raw_text = _strip_code_fence(raw_text)
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, dict) or not data.get("should_write"):
        return []

    lines = data.get("lines")
    if not isinstance(lines, list):
        return []

    parsed = [line for line in (_normalize_memory_line(str(item)) for item in lines) if line]
    return parsed[:3]


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
