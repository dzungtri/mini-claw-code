from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..skills import SkillRegistry
from .envelopes import utc_now_iso


SKILL_HUB_INSTALLS_FILE_NAME = "skill_hub_installs.json"
SKILL_HUB_PROVIDER_CLAWHUB = "clawhub"


@dataclass(slots=True)
class SkillHubCommandResult:
    argv: tuple[str, ...]
    cwd: Path
    exit_code: int
    stdout: str
    stderr: str

    def __post_init__(self) -> None:
        self.argv = tuple(part.strip() for part in self.argv if part.strip())
        self.cwd = Path(self.cwd).expanduser().resolve()
        self.stdout = self.stdout.strip()
        self.stderr = self.stderr.strip()

    def require_success(self, action: str) -> "SkillHubCommandResult":
        if self.exit_code == 0:
            return self
        detail = self.stderr or self.stdout or "unknown error"
        raise RuntimeError(f"{action} failed: {detail}")


@dataclass(slots=True)
class SkillHubInstallRecord:
    provider: str
    slug: str
    scope: str
    workdir: Path
    install_dir: str
    version: str
    installed_at: str
    updated_at: str
    command_prefix: tuple[str, ...]

    def __post_init__(self) -> None:
        self.provider = self.provider.strip()
        self.slug = self.slug.strip()
        self.scope = self.scope.strip() or "project"
        self.workdir = Path(self.workdir).expanduser().resolve()
        self.install_dir = self.install_dir.strip() or ".agents/skills"
        self.version = self.version.strip()
        self.command_prefix = tuple(part.strip() for part in self.command_prefix if part.strip())
        if not self.provider:
            raise ValueError("provider cannot be empty")
        if not self.slug:
            raise ValueError("slug cannot be empty")

    @property
    def install_root(self) -> Path:
        return (self.workdir / self.install_dir).resolve()

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.scope}:{self.slug}"

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, object]) -> "SkillHubInstallRecord":
        payload = dict(raw)
        payload["workdir"] = Path(str(payload["workdir"]))
        payload["command_prefix"] = tuple(payload.get("command_prefix", ()))
        return cls(**payload)  # type: ignore[arg-type]


CommandRunner = Callable[[Sequence[str], Path], SkillHubCommandResult]


class ClawHubClient:
    def __init__(
        self,
        *,
        command_prefix: Sequence[str] | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.command_prefix = tuple(command_prefix or default_clawhub_command())
        self.runner = runner or _run_skill_hub_command

    def search(self, query: str, *, limit: int = 5, cwd: Path | None = None) -> SkillHubCommandResult:
        normalized = " ".join(query.split()).strip()
        if not normalized:
            raise ValueError("search query cannot be empty")
        target_cwd = Path.cwd() if cwd is None else Path(cwd)
        argv = [*self.command_prefix, "search", normalized, "--limit", str(limit)]
        return self.runner(argv, target_cwd).require_success("skill search")

    def install(
        self,
        slug: str,
        *,
        workdir: Path,
        install_dir: str = ".agents/skills",
        version: str | None = None,
        force: bool = False,
    ) -> SkillHubCommandResult:
        normalized_slug = slug.strip()
        if not normalized_slug:
            raise ValueError("skill slug cannot be empty")
        argv = [
            *self.command_prefix,
            "install",
            normalized_slug,
            "--workdir",
            str(Path(workdir).expanduser().resolve()),
            "--dir",
            install_dir.strip() or ".agents/skills",
        ]
        if version is not None and version.strip():
            argv.extend(["--version", version.strip()])
        if force:
            argv.append("--force")
        return self.runner(argv, Path(workdir).expanduser().resolve()).require_success("skill install")


class SkillHubInstallStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / SKILL_HUB_INSTALLS_FILE_NAME

    def list(self) -> list[SkillHubInstallRecord]:
        return [SkillHubInstallRecord.from_json_dict(raw) for raw in _read_store(self.path)]

    def upsert(
        self,
        *,
        provider: str,
        slug: str,
        scope: str,
        workdir: Path,
        install_dir: str,
        version: str,
        command_prefix: Sequence[str],
    ) -> SkillHubInstallRecord:
        now = utc_now_iso()
        record = SkillHubInstallRecord(
            provider=provider,
            slug=slug,
            scope=scope,
            workdir=workdir,
            install_dir=install_dir,
            version=version,
            installed_at=now,
            updated_at=now,
            command_prefix=tuple(command_prefix),
        )
        rows = self.list()
        for index, existing in enumerate(rows):
            if existing.key != record.key:
                continue
            record.installed_at = existing.installed_at
            rows[index] = record
            self._write(rows)
            return record
        rows.append(record)
        self._write(rows)
        return record

    def render(self, *, limit: int = 10) -> str:
        records = self.list()
        if not records:
            return "Hub installs: none."
        lines = ["Hub installs:"]
        for record in sorted(records, key=lambda item: item.updated_at, reverse=True)[:limit]:
            version = record.version or "latest"
            lines.append(f"- {record.slug}: provider={record.provider} scope={record.scope} version={version}")
            lines.append(f"  install_root={record.install_root}")
            lines.append(f"  updated={record.updated_at}")
        return "\n".join(lines)

    def _write(self, records: list[SkillHubInstallRecord]) -> None:
        rows = []
        for record in records:
            row = asdict(record)
            row["workdir"] = str(record.workdir)
            rows.append(row)
        _write_store(self.path, rows)


class SkillHubManager:
    def __init__(
        self,
        *,
        cwd: Path,
        home: Path,
        root: Path,
        client: ClawHubClient | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.home = Path(home).expanduser().resolve()
        self.client = client or ClawHubClient()
        self.installs = SkillHubInstallStore(root)

    def search(self, query: str, *, limit: int = 5) -> SkillHubCommandResult:
        return self.client.search(query, limit=limit, cwd=self.cwd)

    def install_project_skill(
        self,
        slug: str,
        *,
        version: str | None = None,
        force: bool = False,
    ) -> SkillHubInstallRecord:
        return self._install(
            slug,
            scope="project",
            workdir=self.cwd,
            version=version,
            force=force,
        )

    def install_user_skill(
        self,
        slug: str,
        *,
        version: str | None = None,
        force: bool = False,
    ) -> SkillHubInstallRecord:
        return self._install(
            slug,
            scope="user",
            workdir=self.home,
            version=version,
            force=force,
        )

    def render(self) -> str:
        registry = SkillRegistry.discover_default(cwd=self.cwd, home=self.home)
        local_summary = (
            "Local skills: none."
            if not registry.all()
            else "Local skills:\n" + "\n".join(f"- {skill.name}: {skill.description}" for skill in registry.all())
        )
        return "\n".join([local_summary, "", self.installs.render()])

    def _install(
        self,
        slug: str,
        *,
        scope: str,
        workdir: Path,
        version: str | None,
        force: bool,
    ) -> SkillHubInstallRecord:
        install_dir = ".agents/skills"
        self.client.install(
            slug,
            workdir=workdir,
            install_dir=install_dir,
            version=version,
            force=force,
        )
        return self.installs.upsert(
            provider=SKILL_HUB_PROVIDER_CLAWHUB,
            slug=slug.strip(),
            scope=scope,
            workdir=workdir,
            install_dir=install_dir,
            version=(version or "").strip(),
            command_prefix=self.client.command_prefix,
        )


def default_clawhub_command() -> tuple[str, ...]:
    if shutil.which("clawhub") is not None:
        return ("clawhub",)
    if shutil.which("npx") is not None:
        return ("npx", "-y", "clawhub")
    raise RuntimeError("clawhub CLI not found. Install `clawhub` or make `npx` available.")


def _run_skill_hub_command(argv: Sequence[str], cwd: Path) -> SkillHubCommandResult:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(Path(cwd).expanduser().resolve()),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"skill hub command not found: {argv[0]}") from exc
    return SkillHubCommandResult(
        argv=tuple(str(part) for part in argv),
        cwd=Path(cwd),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _read_store(path: Path) -> list[dict[str, object]]:
    import json

    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"store must contain a JSON array: {path}")
    return [item for item in raw if isinstance(item, dict)]


def _write_store(path: Path, rows: list[dict[str, object]]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(rows, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temp_path.replace(path)
