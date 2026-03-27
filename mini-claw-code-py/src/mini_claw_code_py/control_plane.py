from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


CONTROL_PLANE_PROMPT_SECTION = """<control_plane>
You are running with control-plane policies enabled.

Core runtime rules:
1. Clarify before acting when requirements are missing, ambiguous, or risky.
2. Use `ask_user` for user-facing clarification or approval.
3. Verify important file changes before claiming success.
4. If you are repeating the same failed action, change strategy instead of retrying blindly.

Clarification-first policy:
- Ask before acting when key details are missing.
- Ask before acting when multiple valid approaches exist.
- Ask before risky or destructive operations.

Verification-before-exit policy:
- After non-trivial writes or edits, verify the result before your final answer.
- Good verification includes reading the changed file, listing outputs, or running tests/checks.
</control_plane>"""


RISKY_BASH_RE = re.compile(
    r"\b(rm\s+-|git\s+reset\s+--hard|git\s+clean\b|sudo\b|chmod\b|chown\b)\b",
    re.IGNORECASE,
)
READ_ONLY_BASH_RE = re.compile(
    r"^\s*(pwd|ls|find|cat|grep|rg|git\s+status|git\s+diff|pytest\b|make\s+test\b)",
    re.IGNORECASE,
)
VERIFY_BASH_RE = re.compile(
    r"^\s*(pytest\b|make\s+test\b|uv\s+run\b|python\s+-m\s+pytest\b|ls\b|find\b|cat\b|grep\b|rg\b|git\s+diff\b|git\s+status\b)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ControlPlaneSettings:
    warn_repeated_tool_calls: int = 3
    block_repeated_tool_calls: int = 5
    audit_limit: int = 200
    require_overwrite_approval: bool = True
    require_risky_bash_approval: bool = True
    warn_on_missing_verification: bool = True


CONTROL_PLANE_PROFILES: dict[str, ControlPlaneSettings] = {
    "safe": ControlPlaneSettings(
        warn_repeated_tool_calls=2,
        block_repeated_tool_calls=4,
        require_overwrite_approval=True,
        require_risky_bash_approval=True,
        warn_on_missing_verification=True,
    ),
    "balanced": ControlPlaneSettings(
        warn_repeated_tool_calls=3,
        block_repeated_tool_calls=5,
        require_overwrite_approval=True,
        require_risky_bash_approval=True,
        warn_on_missing_verification=True,
    ),
    "trusted": ControlPlaneSettings(
        warn_repeated_tool_calls=4,
        block_repeated_tool_calls=6,
        require_overwrite_approval=False,
        require_risky_bash_approval=False,
        warn_on_missing_verification=False,
    ),
}


@dataclass(slots=True)
class AuditEntry:
    kind: str
    message: str


class AuditLog:
    def __init__(self, limit: int = 200) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=limit)

    def push(self, kind: str, message: str) -> None:
        self._entries.append(AuditEntry(kind=kind, message=message))

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def render(self) -> str:
        if not self._entries:
            return "No audit entries yet."
        lines = ["Audit log:"]
        for entry in self._entries:
            lines.append(f"- [{entry.kind}] {entry.message}")
        return "\n".join(lines)


def render_control_plane_prompt_section() -> str:
    return CONTROL_PLANE_PROMPT_SECTION


def control_plane_profile(name: str) -> ControlPlaneSettings:
    profile = CONTROL_PLANE_PROFILES.get(name)
    if profile is None:
        known = ", ".join(sorted(CONTROL_PLANE_PROFILES))
        raise ValueError(f"unknown control-plane profile '{name}' (expected one of: {known})")
    return replace(profile)


def tool_call_signature(name: str, args: object) -> str:
    try:
        blob = json.dumps(args, sort_keys=True, ensure_ascii=True, default=str)
    except TypeError:
        blob = str(args)
    return f"{name}:{blob}"


def classify_loop(
    history: list[str],
    signature: str,
    settings: ControlPlaneSettings,
) -> str | None:
    count = history.count(signature)
    if count >= settings.block_repeated_tool_calls:
        return "block"
    if count >= settings.warn_repeated_tool_calls:
        return "warn"
    return None


def approval_message_for_tool(
    name: str,
    args: object,
    settings: ControlPlaneSettings,
) -> str | None:
    if not isinstance(args, dict):
        return None

    if name == "write" and settings.require_overwrite_approval:
        path = args.get("path")
        if isinstance(path, str) and Path(path).exists():
            return f"Overwrite existing file `{path}`?"

    if name == "bash" and settings.require_risky_bash_approval:
        command = args.get("command")
        if isinstance(command, str) and RISKY_BASH_RE.search(command):
            return f"Run risky shell command `{command}`?"

    return None


def is_mutating_tool(name: str, args: object) -> bool:
    if name in {"write", "edit", "subagent"}:
        return True
    if name != "bash" or not isinstance(args, dict):
        return False
    command = args.get("command")
    if not isinstance(command, str):
        return False
    return not READ_ONLY_BASH_RE.search(command)


def is_verification_tool(name: str, args: object) -> bool:
    if name == "read":
        return True
    if name == "bash" and isinstance(args, dict):
        command = args.get("command")
        return isinstance(command, str) and bool(VERIFY_BASH_RE.search(command))
    if "list_directory" in name or "read" in name or "grep" in name or "glob" in name:
        return True
    return False
