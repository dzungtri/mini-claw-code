from pathlib import Path

from mini_claw_code_py import RouteStore, SessionRouter, SessionStore, default_os_state_root, default_route_store


def test_ch40_route_store_binds_and_resolves_thread_to_session(tmp_path: Path) -> None:
    routes = RouteStore(default_os_state_root(tmp_path))

    bound = routes.bind(
        target_agent="superagent",
        thread_key="cli:local",
        session_id="sess_demo",
    )
    resolved = routes.resolve(target_agent="superagent", thread_key="cli:local")

    assert resolved is not None
    assert resolved.session_id == "sess_demo"
    assert bound.target_agent == "superagent"
    assert (default_os_state_root(tmp_path) / "routes.json").exists()


def test_ch40_session_router_resolve_or_create_reuses_existing_session(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(tmp_path), sessions)

    first_route, first_session = router.resolve_or_create(
        target_agent="superagent",
        thread_key="cli:local",
        cwd=tmp_path,
    )
    second_route, second_session = router.resolve_or_create(
        target_agent="superagent",
        thread_key="cli:local",
        cwd=tmp_path,
    )

    assert first_route.session_id == first_session.id
    assert second_route.session_id == first_session.id
    assert second_session.id == first_session.id


def test_ch40_session_router_recovers_when_route_points_to_missing_session(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path / ".mini-claw" / "sessions")
    router = SessionRouter(default_route_store(tmp_path), sessions)
    router.bind(
        target_agent="superagent",
        thread_key="cli:local",
        session_id="sess_missing",
    )

    route, session = router.resolve_or_create(
        target_agent="superagent",
        thread_key="cli:local",
        cwd=tmp_path,
    )

    assert route.session_id == session.id
    assert session.id != "sess_missing"


def test_ch40_route_rebind_updates_existing_mapping(tmp_path: Path) -> None:
    routes = RouteStore(default_os_state_root(tmp_path))
    first = routes.bind(target_agent="superagent", thread_key="cli:local", session_id="sess_a")
    second = routes.bind(target_agent="superagent", thread_key="cli:local", session_id="sess_b")

    assert first.created_at == second.created_at
    assert second.session_id == "sess_b"
    assert routes.resolve(target_agent="superagent", thread_key="cli:local").session_id == "sess_b"
