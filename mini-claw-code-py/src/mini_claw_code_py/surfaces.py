from __future__ import annotations

from dataclasses import dataclass

from .events import (
    AgentApprovalUpdate,
    AgentArtifactUpdate,
    AgentContextCompaction,
    AgentMemoryUpdate,
    AgentSubagentUpdate,
    AgentTodoUpdate,
    AgentTokenUsage,
)


@dataclass(slots=True)
class SurfaceBlock:
    kind: str
    summary: str
    details: list[str]


def surface_block_for_event(event: object) -> SurfaceBlock | None:
    if isinstance(event, AgentTodoUpdate):
        details = _message_tail_lines(event.message)
        return SurfaceBlock(
            kind="todo",
            summary=f"{event.completed}/{event.total} completed",
            details=details,
        )
    if isinstance(event, AgentSubagentUpdate):
        return SurfaceBlock(
            kind="subagent",
            summary=f"{event.status} {event.index}/{event.total}: {event.brief}",
            details=[],
        )
    if isinstance(event, AgentApprovalUpdate):
        return SurfaceBlock(
            kind="approval",
            summary=f"{event.status} for {event.tool_name}",
            details=[event.message],
        )
    if isinstance(event, AgentMemoryUpdate):
        return SurfaceBlock(
            kind="memory",
            summary=f"{event.status} {event.scope} memory",
            details=[event.message],
        )
    if isinstance(event, AgentContextCompaction):
        trigger = ", ".join(event.triggered_by)
        return SurfaceBlock(
            kind="context",
            summary=f"compacted {event.archived_messages} archived, kept {event.kept_messages} live ({trigger})",
            details=[],
        )
    if isinstance(event, AgentArtifactUpdate):
        return SurfaceBlock(
            kind="artifacts",
            summary=f"{event.created} new, {event.updated} updated, {event.removed} removed",
            details=[],
        )
    if isinstance(event, AgentTokenUsage):
        return SurfaceBlock(
            kind="usage",
            summary=event.message.removeprefix("Token usage: ").strip(),
            details=[],
        )
    return None


def render_surface_block(block: SurfaceBlock) -> list[str]:
    lines = [f"[{block.kind}] {block.summary}"]
    lines.extend(block.details)
    return lines


def render_runtime_status(
    *,
    mode: str,
    control_profile: str | None,
    todo_text: str,
    token_usage_text: str,
    artifact_text: str | None = None,
) -> list[str]:
    lines = [f"Mode: {mode}"]
    if control_profile is not None:
        lines.append(f"Control profile: {control_profile}")
    lines.extend(todo_text.splitlines())
    lines.extend(token_usage_text.splitlines())
    if artifact_text:
        lines.extend(artifact_text.splitlines())
    return lines


def _message_tail_lines(message: str) -> list[str]:
    lines = message.splitlines()
    if len(lines) <= 1:
        return lines
    return lines[1:]
