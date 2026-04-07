from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .types import Message


ARCHIVED_CONTEXT_OPEN = "<archived_context>"
ARCHIVED_CONTEXT_CLOSE = "</archived_context>"


@dataclass(slots=True)
class ContextCompactionSettings:
    max_messages: int = 12
    keep_recent: int = 6
    max_estimated_tokens: int | None = 2400

    def __post_init__(self) -> None:
        if self.keep_recent < 1:
            raise ValueError("keep_recent must be at least 1")
        if self.max_messages <= self.keep_recent:
            raise ValueError("max_messages must be greater than keep_recent")
        if self.max_estimated_tokens is not None and self.max_estimated_tokens < 1:
            raise ValueError("max_estimated_tokens must be positive when provided")


@dataclass(slots=True)
class ContextCompactionResult:
    archived_messages: int
    kept_messages: int
    summary: str
    estimated_tokens_before: int
    estimated_tokens_after: int
    triggered_by: tuple[str, ...]

    def notice(self) -> str:
        triggers = ", ".join(self.triggered_by)
        return (
            "Context compacted: "
            f"archived {self.archived_messages} messages, "
            f"kept {self.kept_messages} live messages, "
            f"estimated tokens {self.estimated_tokens_before}->{self.estimated_tokens_after} "
            f"(trigger: {triggers})."
        )


def compact_message_history(
    messages: list[Message],
    settings: ContextCompactionSettings,
) -> ContextCompactionResult | None:
    if not messages:
        return None

    leading_system, remainder = _split_leading_system(messages)
    prior_archive_parts: list[str] = []
    active: list[Message] = []

    for message in remainder:
        if _is_archived_context_message(message):
            if message.content:
                prior_archive_parts.append(_strip_archive_wrappers(message.content))
            continue
        active.append(message)

    estimated_tokens_before = estimate_messages_tokens(active)
    triggered_by = _compaction_triggers(
        active,
        settings,
        estimated_tokens_before,
    )
    if not triggered_by:
        return None

    archived = active[:-settings.keep_recent]
    recent = active[-settings.keep_recent :]
    summary = render_archived_context(prior_archive_parts, archived)
    summary_message = Message.system(summary)
    estimated_tokens_after = estimate_messages_tokens([summary_message, *recent])

    if estimated_tokens_after >= estimated_tokens_before:
        summary = render_minimal_archived_context(prior_archive_parts, archived)
        summary_message = Message.system(summary)
        estimated_tokens_after = estimate_messages_tokens([summary_message, *recent])

    messages[:] = [*leading_system, summary_message, *recent]
    return ContextCompactionResult(
        archived_messages=len(archived),
        kept_messages=len(recent),
        summary=summary,
        estimated_tokens_before=estimated_tokens_before,
        estimated_tokens_after=estimated_tokens_after,
        triggered_by=tuple(triggered_by),
    )


def render_context_durability_prompt_section() -> str:
    return """<context_durability>
The runtime may compact older conversation history into an archived context summary.

When archived context appears:
- treat it as trusted condensed history from earlier work
- use it to preserve continuity across long tasks
- prefer recent live messages when you need immediate detail
- be aware that compaction may trigger from message count or estimated token budget
</context_durability>"""


def estimate_messages_tokens(messages: list[Message]) -> int:
    total = 0
    for message in messages:
        total += estimate_message_tokens(message)
    return total


def estimate_message_tokens(message: Message) -> int:
    text_parts: list[str] = [message.kind]
    if message.content:
        text_parts.append(message.content)
    if message.turn is not None:
        if message.turn.text:
            text_parts.append(message.turn.text)
        for call in message.turn.tool_calls:
            text_parts.append(call.name)
            try:
                text_parts.append(json.dumps(call.arguments, ensure_ascii=True, sort_keys=True))
            except TypeError:
                text_parts.append(str(call.arguments))
    if message.tool_call_id:
        text_parts.append(message.tool_call_id)
    combined = "\n".join(text_parts)
    # Lightweight heuristic:
    # about 1 token per 4 characters, plus a small fixed per-message overhead.
    return max(1, math.ceil(len(combined) / 4) + 4)


def render_archived_context(
    prior_archive_parts: list[str],
    archived_messages: list[Message],
) -> str:
    lines = [
        ARCHIVED_CONTEXT_OPEN,
        "Older conversation history was compacted to preserve continuity.",
        "Use this summary as durable archived context.",
        "",
    ]

    if prior_archive_parts:
        lines.extend(
            [
                "Earlier archived context:",
                f"- {_shorten(' '.join(part.strip() for part in prior_archive_parts if part.strip()), 280)}",
                "",
            ]
        )

    user_points: list[str] = []
    action_points: list[str] = []
    result_points: list[str] = []
    conclusion_points: list[str] = []

    for message in archived_messages:
        if message.kind == "user":
            if message.content:
                user_points.append(_shorten(message.content))
            continue

        if message.kind == "assistant" and message.turn is not None:
            turn = message.turn
            if turn.tool_calls:
                action_points.append(
                    "used tools: " + ", ".join(f"`{call.name}`" for call in turn.tool_calls)
                )
            if turn.text:
                conclusion_points.append(_shorten(turn.text))
            continue

        if message.kind == "tool_result" and message.content:
            result_points.append(_shorten(message.content))

    _append_section(lines, "User requests and constraints", user_points)
    _append_section(lines, "Assistant actions", action_points)
    _append_section(lines, "Key tool results", result_points)
    _append_section(lines, "Assistant conclusions", conclusion_points)

    if lines[-1] != "":
        lines.append("")
    lines.extend(
        [
            "Prefer the recent live messages for immediate detail and use this archive for continuity.",
            ARCHIVED_CONTEXT_CLOSE,
        ]
    )
    return "\n".join(lines)


def render_minimal_archived_context(
    prior_archive_parts: list[str],
    archived_messages: list[Message],
) -> str:
    points: list[str] = []
    if prior_archive_parts:
        points.append(
            "Earlier archived context: "
            + _shorten(" ".join(part.strip() for part in prior_archive_parts if part.strip()), 240)
        )

    for message in archived_messages:
        if message.kind == "user" and message.content:
            points.append("user: " + _shorten(message.content, 100))
        elif message.kind == "assistant" and message.turn is not None:
            if message.turn.text:
                points.append("assistant: " + _shorten(message.turn.text, 100))
            elif message.turn.tool_calls:
                tool_names = ", ".join(f"`{call.name}`" for call in message.turn.tool_calls[:4])
                points.append("used tools: " + tool_names)
        elif message.kind == "tool_result" and message.content:
            points.append("tool result: " + _shorten(message.content, 100))

    lines = [
        ARCHIVED_CONTEXT_OPEN,
        "Condensed archived context:",
    ]
    for point in points[:5]:
        lines.append(f"- {point}")
    lines.append(ARCHIVED_CONTEXT_CLOSE)
    return "\n".join(lines)


def _split_leading_system(messages: list[Message]) -> tuple[list[Message], list[Message]]:
    if messages and messages[0].kind == "system" and not _is_archived_context_message(messages[0]):
        return [messages[0]], messages[1:]
    return [], list(messages)


def _is_archived_context_message(message: Message) -> bool:
    return (
        message.kind == "system"
        and isinstance(message.content, str)
        and message.content.strip().startswith(ARCHIVED_CONTEXT_OPEN)
    )


def _strip_archive_wrappers(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(ARCHIVED_CONTEXT_OPEN):
        stripped = stripped[len(ARCHIVED_CONTEXT_OPEN) :].strip()
    if stripped.endswith(ARCHIVED_CONTEXT_CLOSE):
        stripped = stripped[: -len(ARCHIVED_CONTEXT_CLOSE)].strip()
    return stripped


def _append_section(lines: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    lines.append(f"{title}:")
    for item in items[:6]:
        lines.append(f"- {item}")
    lines.append("")


def _shorten(text: str, limit: int = 160) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _compaction_triggers(
    active: list[Message],
    settings: ContextCompactionSettings,
    estimated_tokens: int,
) -> list[str]:
    triggers: list[str] = []
    if len(active) > settings.max_messages:
        triggers.append("message_count")
    if (
        settings.max_estimated_tokens is not None
        and estimated_tokens > settings.max_estimated_tokens
    ):
        triggers.append("estimated_tokens")
    return triggers
