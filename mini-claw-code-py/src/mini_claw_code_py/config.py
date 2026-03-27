from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .context import ContextCompactionSettings
from .control_plane import ControlPlaneSettings

if TYPE_CHECKING:
    from .harness import HarnessAgent
    from .tools import InputHandler


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
    control_plane: ControlPlaneSettings = field(default_factory=ControlPlaneSettings)

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
            warn_repeated_tool_calls=config.control_plane.warn_repeated_tool_calls,
            block_repeated_tool_calls=config.control_plane.block_repeated_tool_calls,
            require_overwrite_approval=config.control_plane.require_overwrite_approval,
            require_risky_bash_approval=config.control_plane.require_risky_bash_approval,
            warn_on_missing_verification=config.control_plane.warn_on_missing_verification,
        )
    return agent


def _resolve_optional_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return Path(path).expanduser().resolve()


def _supports_chat(agent: "HarnessAgent") -> bool:
    provider = getattr(agent, "provider", None)
    chat = getattr(provider, "chat", None)
    return callable(chat)
