from pathlib import Path

import pytest

from mini_claw_code_py import (
    ClawHubClient,
    SkillHubCommandResult,
    SkillHubInstallStore,
    SkillHubManager,
    default_clawhub_command,
    default_os_state_root,
)
from mini_claw_code_py.tui.app import _parse_skill_install_args


def test_ch45_default_clawhub_command_prefers_clawhub_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mini_claw_code_py.os.skill_hubs.shutil.which", lambda name: "/usr/bin/clawhub" if name == "clawhub" else None)

    assert default_clawhub_command() == ("clawhub",)


def test_ch45_default_clawhub_command_falls_back_to_npx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mini_claw_code_py.os.skill_hubs.shutil.which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )

    assert default_clawhub_command() == ("npx", "-y", "clawhub")


def test_ch45_clawhub_client_builds_search_command(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_runner(argv: object, cwd: Path) -> SkillHubCommandResult:
        command = tuple(str(part) for part in argv)  # type: ignore[arg-type]
        calls.append((command, cwd))
        return SkillHubCommandResult(argv=command, cwd=cwd, exit_code=0, stdout="result", stderr="")

    client = ClawHubClient(command_prefix=("clawhub",), runner=fake_runner)
    result = client.search("postgres backups", limit=7, cwd=tmp_path)

    assert result.stdout == "result"
    assert calls == [
        (("clawhub", "search", "postgres backups", "--limit", "7"), tmp_path),
    ]


def test_ch45_clawhub_client_builds_install_command(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_runner(argv: object, cwd: Path) -> SkillHubCommandResult:
        command = tuple(str(part) for part in argv)  # type: ignore[arg-type]
        calls.append((command, cwd))
        return SkillHubCommandResult(argv=command, cwd=cwd, exit_code=0, stdout="installed", stderr="")

    client = ClawHubClient(command_prefix=("npx", "-y", "clawhub"), runner=fake_runner)
    result = client.install(
        "calendar-helper",
        workdir=tmp_path,
        install_dir=".agents/skills",
        version="1.2.3",
        force=True,
    )

    assert result.stdout == "installed"
    assert calls == [
        (
            (
                "npx",
                "-y",
                "clawhub",
                "install",
                "calendar-helper",
                "--workdir",
                str(tmp_path.resolve()),
                "--dir",
                ".agents/skills",
                "--version",
                "1.2.3",
                "--force",
            ),
            tmp_path.resolve(),
        ),
    ]


def test_ch45_parse_skill_install_args_supports_user_version_and_force() -> None:
    parsed = _parse_skill_install_args(
        "/skill install calendar-helper --user --version 1.2.3 --force",
        slug_index=2,
    )

    assert parsed == {
        "slug": "calendar-helper",
        "version": "1.2.3",
        "force": True,
        "install_user": True,
    }


def test_ch45_skill_hub_manager_installs_project_and_user_scopes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    calls: list[tuple[str, Path, str, str | None, bool]] = []

    class FakeClient:
        command_prefix = ("clawhub",)

        def install(
            self,
            slug: str,
            *,
            workdir: Path,
            install_dir: str,
            version: str | None = None,
            force: bool = False,
        ) -> SkillHubCommandResult:
            calls.append((slug, workdir, install_dir, version, force))
            return SkillHubCommandResult(
                argv=("clawhub", "install", slug),
                cwd=workdir,
                exit_code=0,
                stdout="ok",
                stderr="",
            )

    manager = SkillHubManager(
        cwd=project,
        home=home,
        root=default_os_state_root(project),
        client=FakeClient(),  # type: ignore[arg-type]
    )

    project_record = manager.install_project_skill("calendar-helper", version="1.0.0")
    user_record = manager.install_user_skill("jira-helper", force=True)

    assert project_record.scope == "project"
    assert project_record.install_root == (project / ".agents" / "skills").resolve()
    assert user_record.scope == "user"
    assert user_record.install_root == (home / ".agents" / "skills").resolve()
    assert calls == [
        ("calendar-helper", project, ".agents/skills", "1.0.0", False),
        ("jira-helper", home, ".agents/skills", None, True),
    ]


def test_ch45_skill_hub_install_store_is_file_backed_and_renderable(tmp_path: Path) -> None:
    store = SkillHubInstallStore(default_os_state_root(tmp_path))

    first = store.upsert(
        provider="clawhub",
        slug="calendar-helper",
        scope="project",
        workdir=tmp_path,
        install_dir=".agents/skills",
        version="1.0.0",
        command_prefix=("clawhub",),
    )
    second = store.upsert(
        provider="clawhub",
        slug="calendar-helper",
        scope="project",
        workdir=tmp_path,
        install_dir=".agents/skills",
        version="1.1.0",
        command_prefix=("clawhub",),
    )

    assert first.installed_at == second.installed_at
    assert store.list()[0].version == "1.1.0"
    assert "calendar-helper" in store.render()
    assert "1.1.0" in store.render()


def test_ch45_skill_hub_manager_render_includes_local_skills_and_install_history(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    skill_root = project / ".agents" / "skills" / "calendar-helper"
    skill_root.mkdir(parents=True)
    project.mkdir(exist_ok=True)
    home.mkdir(exist_ok=True)
    (skill_root / "SKILL.md").write_text(
        (
            "---\n"
            "name: calendar-helper\n"
            "description: Calendar workflow helper.\n"
            "---\n"
            "\n"
            "Use this skill for calendar workflows.\n"
        ),
        encoding="utf-8",
    )
    store = SkillHubInstallStore(default_os_state_root(project))
    store.upsert(
        provider="clawhub",
        slug="calendar-helper",
        scope="project",
        workdir=project,
        install_dir=".agents/skills",
        version="",
        command_prefix=("clawhub",),
    )

    manager = SkillHubManager(
        cwd=project,
        home=home,
        root=default_os_state_root(project),
        client=ClawHubClient(command_prefix=("clawhub",), runner=lambda argv, cwd: SkillHubCommandResult(tuple(argv), cwd, 0, "", "")),
    )

    rendered = manager.render()

    assert "Local skills:" in rendered
    assert "calendar-helper" in rendered
    assert "Hub installs:" in rendered
