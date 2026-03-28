from pathlib import Path

import pytest

from mini_claw_code_py import (
    GOAL_STATUSES,
    RUN_STATUSES,
    TASK_STATUSES,
    TEAM_CONFIG_FILE_NAME,
    GoalStore,
    RunStore,
    TaskStore,
    TeamRegistry,
    default_os_state_root,
    default_team_config_paths,
    parse_team_registry,
)


def test_ch39_default_team_config_paths_follow_user_then_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / TEAM_CONFIG_FILE_NAME).write_text('{"teams": {}}\n', encoding="utf-8")
    (project / TEAM_CONFIG_FILE_NAME).write_text('{"teams": {}}\n', encoding="utf-8")

    paths = default_team_config_paths(cwd=project, home=home)

    assert paths == [
        (home / TEAM_CONFIG_FILE_NAME).resolve(),
        (project / TEAM_CONFIG_FILE_NAME).resolve(),
    ]


def test_ch39_team_registry_discovers_default_team_when_no_files_exist(tmp_path: Path) -> None:
    registry = TeamRegistry.discover_default(cwd=tmp_path / "project", home=tmp_path / "home")

    default_team = registry.require("default")
    assert default_team.lead_agent == "superagent"
    assert default_team.member_agents == ("superagent",)


def test_ch39_team_registry_merges_user_and_project_fields(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / TEAM_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "product-a": {\n'
            '      "description": "General delivery team.",\n'
            '      "lead_agent": "superagent",\n'
            '      "member_agents": ["backend-dev", "frontend-dev"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (project / TEAM_CONFIG_FILE_NAME).write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "product-a": {\n'
            '      "description": "Project A delivery team."\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    registry = TeamRegistry.discover_default(cwd=project, home=home)
    team = registry.require("product-a")

    assert team.description == "Project A delivery team."
    assert team.lead_agent == "superagent"
    assert team.member_agents == ("backend-dev", "frontend-dev")


def test_ch39_parse_team_registry_reads_explicit_team_file(tmp_path: Path) -> None:
    config_path = tmp_path / TEAM_CONFIG_FILE_NAME
    config_path.write_text(
        (
            '{\n'
            '  "teams": {\n'
            '    "marketing": {\n'
            '      "description": "Marketing team.",\n'
            '      "lead_agent": "marketing-lead",\n'
            '      "member_agents": ["copywriter", "seo-agent"]\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    parsed = parse_team_registry(config_path)

    assert parsed["marketing"].lead_agent == "marketing-lead"
    assert parsed["marketing"].member_agents == ("copywriter", "seo-agent")


def test_ch39_goal_task_and_run_stores_are_file_backed_and_filterable(tmp_path: Path) -> None:
    root = default_os_state_root(tmp_path)
    goals = GoalStore(root)
    tasks = TaskStore(root)
    runs = RunStore(root)

    goal = goals.create(
        title="Build the release candidate",
        description="Coordinate implementation and verification.",
        primary_team="product-a",
    )
    task = tasks.assign(
        goal_id=goal.goal_id,
        team_id="product-a",
        agent_name="backend-dev",
        title="Implement the release changes",
    )
    run = runs.start(
        task_id=task.task_id,
        agent_name="backend-dev",
        source="cli",
        thread_key="cli:local",
        session_id="sess_demo",
        trace_id="trace_demo",
    )

    assert goals.get(goal.goal_id) is not None
    assert tasks.get(task.task_id) is not None
    assert runs.get(run.run_id) is not None
    assert [record.task_id for record in tasks.list(goal_id=goal.goal_id)] == [task.task_id]
    assert [record.run_id for record in runs.list(task_id=task.task_id)] == [run.run_id]
    assert run.source == "cli"
    assert run.thread_key == "cli:local"

    completed_goal = goals.update_status(goal.goal_id, "completed")
    blocked_task = tasks.update_status(task.task_id, "blocked")
    completed_run = runs.finish(run.run_id, status="completed")

    assert completed_goal.status == "completed"
    assert blocked_task.status == "blocked"
    assert completed_run.status == "completed"
    assert completed_run.finished_at is not None
    assert (root / "goals.json").exists()
    assert (root / "tasks.json").exists()
    assert (root / "runs.json").exists()


def test_ch39_status_constants_and_validation_are_explicit(tmp_path: Path) -> None:
    assert GOAL_STATUSES == ("pending", "in_progress", "blocked", "completed")
    assert TASK_STATUSES == ("pending", "in_progress", "blocked", "completed")
    assert RUN_STATUSES == ("running", "completed", "failed", "cancelled")

    root = default_os_state_root(tmp_path)
    goals = GoalStore(root)
    goal = goals.create(title="Demo", description="", primary_team="default")

    with pytest.raises(ValueError, match="unsupported goal status"):
        goals.update_status(goal.goal_id, "done")
