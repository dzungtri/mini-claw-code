from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import ToolDefinition


WORKSPACE_PREFIX = "workspace://"
SCRATCH_PREFIX = "scratch://"
OUTPUTS_PREFIX = "outputs://"
UPLOADS_PREFIX = "uploads://"

_DESTRUCTIVE_BASH_PATTERNS = [
    re.compile(r"(^|[;&|]\s*)rm\s+-rf\s+/"),
    re.compile(r"(^|[;&|]\s*)sudo\b"),
    re.compile(r"(^|[;&|]\s*)git\s+reset\s+--hard\b"),
    re.compile(r"(^|[;&|]\s*)git\s+checkout\s+--\b"),
]


@dataclass(slots=True)
class WorkspaceConfig:
    root: Path
    scratch: Path | None = None
    outputs: Path | None = None
    uploads: Path | None = None
    allow_destructive_bash: bool = False

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve()
        self.scratch = _resolve_child_config_path(self.root, self.scratch)
        self.outputs = _resolve_child_config_path(self.root, self.outputs)
        self.uploads = _resolve_child_config_path(self.root, self.uploads)

    def status_summary(self) -> str:
        parts = [f"root={self.root}"]
        if self.scratch is not None:
            parts.append(f"scratch={self.scratch}")
        if self.outputs is not None:
            parts.append(f"outputs={self.outputs}")
        if self.uploads is not None:
            parts.append(f"uploads={self.uploads}")
        return "Workspace ready: " + ", ".join(parts)

    def shell_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["MINI_CLAW_WORKSPACE_ROOT"] = str(self.root)
        if self.scratch is not None:
            env["MINI_CLAW_SCRATCH_DIR"] = str(self.scratch)
        if self.outputs is not None:
            env["MINI_CLAW_OUTPUTS_DIR"] = str(self.outputs)
        if self.uploads is not None:
            env["MINI_CLAW_UPLOADS_DIR"] = str(self.uploads)
        return env


def render_workspace_prompt_section(config: WorkspaceConfig) -> str:
    lines = [
        "<workspace>",
        f"Workspace root: {config.root}",
        "Relative paths resolve against the workspace root.",
        f"- {WORKSPACE_PREFIX} maps to the workspace root",
    ]
    if config.scratch is not None:
        lines.append(f"- {SCRATCH_PREFIX} maps to {config.scratch}")
    if config.outputs is not None:
        lines.append(f"- {OUTPUTS_PREFIX} maps to {config.outputs}")
    if config.uploads is not None:
        lines.append(f"- {UPLOADS_PREFIX} maps to {config.uploads}")
    lines.extend(
        [
            "Shell commands run with cwd set to the workspace root.",
            "The shell also receives MINI_CLAW_WORKSPACE_ROOT and other workspace env vars when available.",
        ]
    )
    if not config.allow_destructive_bash:
        lines.append("Obvious destructive bash commands are blocked by the first sandbox policy.")
    lines.append("</workspace>")
    return "\n".join(lines)


def resolve_workspace_path(
    raw_path: str,
    config: WorkspaceConfig,
) -> Path:
    if not raw_path.strip():
        raise ValueError("path must not be empty")

    alias_base, relative = _parse_workspace_alias(raw_path, config)
    if alias_base is not None:
        candidate = (alias_base / relative).resolve()
        if not is_within_workspace(candidate, alias_base):
            raise PermissionError(f"path escapes {alias_base}: {raw_path}")
        return candidate

    input_path = Path(raw_path).expanduser()
    candidate = (config.root / input_path).resolve() if not input_path.is_absolute() else input_path.resolve()
    if not is_allowed_workspace_path(candidate, config):
        raise PermissionError(f"path is outside the workspace: {raw_path}")
    return candidate


def is_allowed_workspace_path(path: Path, config: WorkspaceConfig) -> bool:
    for root in allowed_workspace_roots(config):
        if is_within_workspace(path, root):
            return True
    return False


def allowed_workspace_roots(config: WorkspaceConfig) -> list[Path]:
    roots = [config.root]
    for path in [config.scratch, config.outputs, config.uploads]:
        if path is not None and path not in roots:
            roots.append(path)
    return roots


def is_within_workspace(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_bash_command(command: str, *, allow_destructive: bool) -> None:
    if allow_destructive:
        return
    normalized = command.strip()
    for pattern in _DESTRUCTIVE_BASH_PATTERNS:
        if pattern.search(normalized):
            raise PermissionError("blocked potentially destructive bash command")


class WorkspaceReadTool:
    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self._definition = ToolDefinition.new(
            "read",
            "Read the contents of a file within the workspace boundary.",
        ).param("path", "string", "The file path to read", True)

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        path = args.get("path") if isinstance(args, dict) else None
        if not isinstance(path, str):
            raise ValueError("missing 'path' argument")
        target = resolve_workspace_path(path, self.config)
        try:
            return await asyncio.to_thread(target.read_text)
        except Exception as exc:
            raise RuntimeError(f"failed to read '{path}'") from exc


class WorkspaceWriteTool:
    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self._definition = (
            ToolDefinition.new(
                "write",
                "Write content to a file within the workspace boundary.",
            )
            .param("path", "string", "The file path to write to", True)
            .param("content", "string", "The content to write to the file", True)
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        path = args.get("path") if isinstance(args, dict) else None
        content = args.get("content") if isinstance(args, dict) else None
        if not isinstance(path, str):
            raise ValueError("missing 'path' argument")
        if not isinstance(content, str):
            raise ValueError("missing 'content' argument")

        target = resolve_workspace_path(path, self.config)
        if target.parent:
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(target.write_text, content)
        except Exception as exc:
            raise RuntimeError(f"failed to write '{path}'") from exc
        return f"wrote {target}"


class WorkspaceEditTool:
    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self._definition = (
            ToolDefinition.new(
                "edit",
                "Replace an exact string in a workspace file (must appear exactly once).",
            )
            .param("path", "string", "The file path to edit", True)
            .param("old_string", "string", "The exact string to find and replace", True)
            .param("new_string", "string", "The replacement string", True)
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        path = args.get("path") if isinstance(args, dict) else None
        old = args.get("old_string") if isinstance(args, dict) else None
        new = args.get("new_string") if isinstance(args, dict) else None
        if not isinstance(path, str):
            raise ValueError("missing 'path' argument")
        if not isinstance(old, str):
            raise ValueError("missing 'old_string' argument")
        if not isinstance(new, str):
            raise ValueError("missing 'new_string' argument")

        target = resolve_workspace_path(path, self.config)
        try:
            content = await asyncio.to_thread(target.read_text)
        except Exception as exc:
            raise RuntimeError(f"failed to read '{path}'") from exc

        count = content.count(old)
        if count == 0:
            raise ValueError(f"old_string not found in '{path}'")
        if count > 1:
            raise ValueError(f"old_string appears {count} times in '{path}', must be unique")

        updated = content.replace(old, new, 1)
        try:
            await asyncio.to_thread(target.write_text, updated)
        except Exception as exc:
            raise RuntimeError(f"failed to write '{path}'") from exc
        return f"edited {target}"


class WorkspaceBashTool:
    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self._definition = ToolDefinition.new(
            "bash",
            "Run a bash command from the workspace root with lightweight sandbox checks.",
        ).param("command", "string", "The bash command to run", True)

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        command = args.get("command") if isinstance(args, dict) else None
        if not isinstance(command, str):
            raise ValueError("missing 'command' argument")

        validate_bash_command(
            command,
            allow_destructive=self.config.allow_destructive_bash,
        )
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            command,
            cwd=str(self.config.root),
            env=self.config.shell_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"stderr: {stderr}")
        if not parts:
            return "(no output)"
        return "\n".join(parts)


def _resolve_child_config_path(root: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    return (root / expanded).resolve() if not expanded.is_absolute() else expanded.resolve()


def _parse_workspace_alias(raw_path: str, config: WorkspaceConfig) -> tuple[Path | None, str]:
    for prefix, base in [
        (WORKSPACE_PREFIX, config.root),
        (SCRATCH_PREFIX, config.scratch),
        (OUTPUTS_PREFIX, config.outputs),
        (UPLOADS_PREFIX, config.uploads),
    ]:
        if not raw_path.startswith(prefix):
            continue
        if base is None:
            raise ValueError(f"{prefix} is not configured in this workspace")
        relative = raw_path[len(prefix) :].lstrip("/")
        return base, relative
    return None, ""
