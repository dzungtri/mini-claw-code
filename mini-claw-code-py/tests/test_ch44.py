from pathlib import Path

from mini_claw_code_py import (
    CHANNEL_CONFIG_FILE_NAME,
    TEAM_CONFIG_FILE_NAME,
    ChannelRegistry,
    TeamRegistry,
    default_channel_config_paths,
    parse_channel_registry,
)
from mini_claw_code_py.tui.app import resolve_cli_route


def test_ch44_default_channel_config_paths_follow_user_then_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / CHANNEL_CONFIG_FILE_NAME).write_text('{"channels": {}}\n', encoding="utf-8")
    (project / CHANNEL_CONFIG_FILE_NAME).write_text('{"channels": {}}\n', encoding="utf-8")

    paths = default_channel_config_paths(cwd=project, home=home)

    assert paths == [
        (home / CHANNEL_CONFIG_FILE_NAME).resolve(),
        (project / CHANNEL_CONFIG_FILE_NAME).resolve(),
    ]


def test_ch44_channel_registry_discovers_default_cli_channel_when_no_files_exist(tmp_path: Path) -> None:
    registry = ChannelRegistry.discover_default(cwd=tmp_path / "project", home=tmp_path / "home")

    channel = registry.require("cli")
    assert channel.default_target_agent == "superagent"
    assert channel.resolve_thread_key("local") == "cli:local"


def test_ch44_channel_registry_merges_user_and_project_fields(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "cli": {\n'
            '      "description": "General terminal front door.",\n'
            '      "default_target_agent": "superagent",\n'
            '      "thread_prefix": "terminal"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (project / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "cli": {\n'
            '      "description": "Project terminal front door."\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    registry = ChannelRegistry.discover_default(cwd=project, home=home)
    cli = registry.require("cli")

    assert cli.description == "Project terminal front door."
    assert cli.default_target_agent == "superagent"
    assert cli.thread_prefix == "terminal"


def test_ch44_parse_channel_registry_reads_explicit_channel_file(tmp_path: Path) -> None:
    config_path = tmp_path / CHANNEL_CONFIG_FILE_NAME
    config_path.write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "telegram": {\n'
            '      "description": "Telegram front door.",\n'
            '      "default_target_agent": "support-agent",\n'
            '      "thread_prefix": "tg"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    parsed = parse_channel_registry(config_path)

    assert parsed["telegram"].default_target_agent == "support-agent"
    assert parsed["telegram"].resolve_thread_key("123") == "tg:123"


def test_ch44_cli_route_can_resolve_target_agent_from_default_team(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (project / TEAM_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "support": {\n'
            '      "description": "Support team.",\n'
            '      "lead_agent": "support-lead",\n'
            '      "member_agents": ["support-lead", "triage-bot"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (project / CHANNEL_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "channels": {\n'
            '    "cli": {\n'
            '      "description": "Support terminal front door.",\n'
            '      "default_team": "support",\n'
            '      "thread_prefix": "cli"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    teams = TeamRegistry.discover_default(cwd=project, home=home)
    _, target_agent, thread_key = resolve_cli_route(cwd=project, home=home, teams=teams)

    assert target_agent == "support-lead"
    assert thread_key == "cli:local"


def test_ch44_team_registry_reads_workspace_root_and_renders_it(tmp_path: Path) -> None:
    config_path = tmp_path / TEAM_CONFIG_FILE_NAME
    config_path.write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "marketing": {\n'
            '      "description": "Marketing team.",\n'
            '      "lead_agent": "marketing-lead",\n'
            '      "member_agents": ["copywriter", "seo-agent"],\n'
            '      "workspace_root": "workspaces/marketing"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    registry = TeamRegistry.discover([config_path])
    team = registry.require("marketing")

    assert team.workspace_root == (tmp_path / "workspaces" / "marketing").resolve()
    assert str(team.workspace_root) in registry.render()
