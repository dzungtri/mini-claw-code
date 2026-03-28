from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from .context import ContextCompactionSettings
from .control_plane import ControlPlaneSettings

if TYPE_CHECKING:
    from .harness import HarnessAgent
    from .tools import InputHandler


CONFIG_FILE_NAME = ".mini-claw.json"
CONFIG_PATH_ENV = "MINI_CLAW_CONFIG"
CONTROL_PROFILE_ENV = "MINI_CLAW_PROFILE"


@dataclass(slots=True)
class WorkspacePathsConfig:
    root: Path
    scratch: Path | None = None
    outputs: Path | None = None
    uploads: Path | None = None
    allow_destructive_bash: bool = False

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()
        self.scratch = _resolve_optional_path(self.scratch)
        self.outputs = _resolve_optional_path(self.outputs)
        self.uploads = _resolve_optional_path(self.uploads)


@dataclass(slots=True)
class HarnessConfig:
    cwd: Path
    home: Path
    workspace: WorkspacePathsConfig
    enable_default_memory: bool = True
    enable_memory_updates: bool = True
    memory_update_scope: str = "user"
    memory_update_debounce_seconds: float = 2.0
    enable_context_durability: bool = True
    context: ContextCompactionSettings = field(default_factory=ContextCompactionSettings)
    enable_subagents: bool = True
    subagent_max_parallel: int = 2
    subagent_max_turns: int = 8
    enable_mcp: bool = True
    enable_tool_universe: bool = True
    enable_skills: bool = True
    enable_control_plane: bool = True
    control_plane_profile: str = "balanced"
    control_plane: ControlPlaneSettings = field(default_factory=ControlPlaneSettings)
    enable_token_usage_tracing: bool = True

    def __post_init__(self) -> None:
        self.cwd = Path(self.cwd).expanduser().resolve()
        self.home = Path(self.home).expanduser().resolve()

    @classmethod
    def default(
        cls,
        *,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> "HarnessConfig":
        target_cwd = Path.cwd() if cwd is None else cwd
        target_home = Path.home() if home is None else home
        return cls(
            cwd=target_cwd,
            home=target_home,
            workspace=WorkspacePathsConfig(
                root=target_cwd,
                scratch=Path(target_cwd) / ".agent-work",
                outputs=Path(target_cwd) / "outputs",
            ),
        )


def default_harness_config(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> HarnessConfig:
    return HarnessConfig.default(cwd=cwd, home=home)


def default_harness_config_paths(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    target_home = Path.home() if home is None else Path(home)
    environ = os.environ if env is None else env

    paths: list[Path] = []
    home_path = (target_home / CONFIG_FILE_NAME).expanduser().resolve()
    if home_path.exists():
        paths.append(home_path)

    project_path = (target_cwd / CONFIG_FILE_NAME).expanduser().resolve()
    if project_path.exists() and project_path != home_path:
        paths.append(project_path)

    explicit = environ.get(CONFIG_PATH_ENV, "").strip()
    if explicit:
        explicit_path = Path(explicit).expanduser().resolve()
        if not explicit_path.exists():
            raise FileNotFoundError(f"{CONFIG_PATH_ENV} points to a missing file: {explicit_path}")
        paths.append(explicit_path)

    return paths


def load_harness_config(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> HarnessConfig:
    target_cwd = Path.cwd() if cwd is None else Path(cwd)
    target_home = Path.home() if home is None else Path(home)
    environ = os.environ if env is None else env

    config = default_harness_config(cwd=target_cwd, home=target_home)
    for path in default_harness_config_paths(cwd=target_cwd, home=target_home, env=environ):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"config file must contain a JSON object: {path}")
        config = _merge_harness_config(config, raw, base_dir=path.parent)

    profile = environ.get(CONTROL_PROFILE_ENV, "").strip()
    if profile:
        config = replace(config, control_plane_profile=profile)

    return config


def apply_harness_config(
    agent: "HarnessAgent",
    config: HarnessConfig,
    *,
    handler: "InputHandler | None" = None,
) -> "HarnessAgent":
    supports_chat = _supports_chat(agent)

    agent.enable_core_tools(handler)
    agent.enable_workspace(
        config.workspace.root,
        scratch=config.workspace.scratch,
        outputs=config.workspace.outputs,
        uploads=config.workspace.uploads,
        allow_destructive_bash=config.workspace.allow_destructive_bash,
    )

    if config.enable_default_memory:
        agent.enable_default_memory(cwd=config.cwd, home=config.home)
    if config.enable_memory_updates and supports_chat:
        agent.enable_memory_updates(
            debounce_seconds=config.memory_update_debounce_seconds,
            target_scope=config.memory_update_scope,
        )
    if config.enable_context_durability:
        agent.enable_context_durability(
            max_messages=config.context.max_messages,
            keep_recent=config.context.keep_recent,
            max_estimated_tokens=config.context.max_estimated_tokens,
        )
    if config.enable_subagents and supports_chat:
        agent.enable_subagents(
            max_parallel_subagents=config.subagent_max_parallel,
            max_turns=config.subagent_max_turns,
        )
    if config.enable_mcp:
        agent.enable_default_mcp(cwd=config.cwd, home=config.home)
    if config.enable_tool_universe:
        agent.enable_tool_universe_management()
    if config.enable_skills:
        agent.enable_default_skills(config.cwd)
    if config.enable_control_plane:
        agent.enable_control_plane(
            profile=config.control_plane_profile,
            warn_repeated_tool_calls=config.control_plane.warn_repeated_tool_calls,
            block_repeated_tool_calls=config.control_plane.block_repeated_tool_calls,
            require_overwrite_approval=config.control_plane.require_overwrite_approval,
            require_risky_bash_approval=config.control_plane.require_risky_bash_approval,
            warn_on_missing_verification=config.control_plane.warn_on_missing_verification,
        )
    if config.enable_token_usage_tracing:
        agent.enable_token_usage_tracing()
    return agent


def _resolve_optional_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return Path(path).expanduser().resolve()


def _supports_chat(agent: "HarnessAgent") -> bool:
    provider = getattr(agent, "provider", None)
    chat = getattr(provider, "chat", None)
    return callable(chat)


def _merge_harness_config(
    config: HarnessConfig,
    raw: dict[str, object],
    *,
    base_dir: Path,
) -> HarnessConfig:
    merged = config

    workspace = raw.get("workspace")
    if workspace is not None:
        if not isinstance(workspace, dict):
            raise ValueError("workspace must be an object")
        merged = replace(
            merged,
            workspace=WorkspacePathsConfig(
                root=_resolve_config_path(workspace.get("root"), base_dir, merged.workspace.root),
                scratch=_resolve_config_optional_path(workspace.get("scratch"), base_dir, merged.workspace.scratch),
                outputs=_resolve_config_optional_path(workspace.get("outputs"), base_dir, merged.workspace.outputs),
                uploads=_resolve_config_optional_path(workspace.get("uploads"), base_dir, merged.workspace.uploads),
                allow_destructive_bash=_coerce_bool(
                    workspace.get("allow_destructive_bash"),
                    merged.workspace.allow_destructive_bash,
                ),
            ),
        )

    context = raw.get("context")
    if context is not None:
        if not isinstance(context, dict):
            raise ValueError("context must be an object")
        merged = replace(
            merged,
            context=ContextCompactionSettings(
                max_messages=_coerce_int(context.get("max_messages"), merged.context.max_messages),
                keep_recent=_coerce_int(context.get("keep_recent"), merged.context.keep_recent),
                max_estimated_tokens=_coerce_optional_int(
                    context.get("max_estimated_tokens"),
                    merged.context.max_estimated_tokens,
                ),
            ),
        )

    memory_updates = raw.get("memory_updates")
    if memory_updates is not None:
        if not isinstance(memory_updates, dict):
            raise ValueError("memory_updates must be an object")
        scope = memory_updates.get("scope", merged.memory_update_scope)
        if not isinstance(scope, str):
            raise ValueError("memory_updates.scope must be a string")
        merged = replace(
            merged,
            memory_update_scope=scope,
            memory_update_debounce_seconds=_coerce_float(
                memory_updates.get("debounce_seconds"),
                merged.memory_update_debounce_seconds,
            ),
        )

    subagents = raw.get("subagents")
    if subagents is not None:
        if not isinstance(subagents, dict):
            raise ValueError("subagents must be an object")
        merged = replace(
            merged,
            subagent_max_parallel=_coerce_int(
                subagents.get("max_parallel"),
                merged.subagent_max_parallel,
            ),
            subagent_max_turns=_coerce_int(
                subagents.get("max_turns"),
                merged.subagent_max_turns,
            ),
        )

    control_plane = raw.get("control_plane")
    if control_plane is not None:
        if not isinstance(control_plane, dict):
            raise ValueError("control_plane must be an object")
        merged = replace(
            merged,
            control_plane=ControlPlaneSettings(
                warn_repeated_tool_calls=_coerce_int(
                    control_plane.get("warn_repeated_tool_calls"),
                    merged.control_plane.warn_repeated_tool_calls,
                ),
                block_repeated_tool_calls=_coerce_int(
                    control_plane.get("block_repeated_tool_calls"),
                    merged.control_plane.block_repeated_tool_calls,
                ),
                audit_limit=_coerce_int(
                    control_plane.get("audit_limit"),
                    merged.control_plane.audit_limit,
                ),
                require_overwrite_approval=_coerce_bool(
                    control_plane.get("require_overwrite_approval"),
                    merged.control_plane.require_overwrite_approval,
                ),
                require_risky_bash_approval=_coerce_bool(
                    control_plane.get("require_risky_bash_approval"),
                    merged.control_plane.require_risky_bash_approval,
                ),
                warn_on_missing_verification=_coerce_bool(
                    control_plane.get("warn_on_missing_verification"),
                    merged.control_plane.warn_on_missing_verification,
                ),
            ),
        )

    for key, attr in (
        ("enable_default_memory", "enable_default_memory"),
        ("enable_memory_updates", "enable_memory_updates"),
        ("enable_context_durability", "enable_context_durability"),
        ("enable_subagents", "enable_subagents"),
        ("enable_mcp", "enable_mcp"),
        ("enable_tool_universe", "enable_tool_universe"),
        ("enable_skills", "enable_skills"),
        ("enable_control_plane", "enable_control_plane"),
        ("enable_token_usage_tracing", "enable_token_usage_tracing"),
    ):
        if key in raw:
            merged = replace(merged, **{attr: _coerce_bool(raw[key], getattr(merged, attr))})

    if "control_plane_profile" in raw:
        profile = raw["control_plane_profile"]
        if not isinstance(profile, str):
            raise ValueError("control_plane_profile must be a string")
        merged = replace(merged, control_plane_profile=profile)

    if "cwd" in raw:
        merged = replace(merged, cwd=_resolve_config_path(raw["cwd"], base_dir, merged.cwd))
    if "home" in raw:
        merged = replace(merged, home=_resolve_config_path(raw["home"], base_dir, merged.home))

    return merged


def _resolve_config_path(value: object, base_dir: Path, current: Path) -> Path:
    if value is None:
        return current
    if not isinstance(value, str):
        raise ValueError("path values must be strings")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _resolve_config_optional_path(value: object, base_dir: Path, current: Path | None) -> Path | None:
    if value is None:
        return current
    return _resolve_config_path(value, base_dir, current or base_dir)


def _coerce_bool(value: object, current: bool) -> bool:
    if value is None:
        return current
    if isinstance(value, bool):
        return value
    raise ValueError("expected a boolean value")


def _coerce_int(value: object, current: int) -> int:
    if value is None:
        return current
    if isinstance(value, int):
        return value
    raise ValueError("expected an integer value")


def _coerce_optional_int(value: object, current: int | None) -> int | None:
    if value is None:
        return current
    if isinstance(value, int):
        return value
    raise ValueError("expected an integer or null value")


def _coerce_float(value: object, current: float) -> float:
    if value is None:
        return current
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError("expected a numeric value")
