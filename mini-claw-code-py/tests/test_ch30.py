from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import HarnessAgent, Message, MockStreamProvider, SessionStore, StopReason
from mini_claw_code_py.types import AssistantTurn


def test_ch30_rename_persists_normalized_session_title(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    record = store.create(cwd=tmp_path)

    renamed = store.rename(record, "   Parser   Refactor   Session   ")
    loaded = store.load(renamed.id)

    assert renamed.title == "Parser Refactor Session"
    assert loaded.title == "Parser Refactor Session"


def test_ch30_rename_rejects_empty_title(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    record = store.create(cwd=tmp_path)

    with pytest.raises(ValueError, match="session title cannot be empty"):
        store.rename(record, "   ")


def test_ch30_fork_creates_new_session_and_copies_blob_content(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions", blob_threshold_chars=10)
    source = store.create(cwd=tmp_path, title="Original Work")
    source = store.save_runtime(
        source,
        messages=[
            Message.user("Write a long answer."),
            Message.assistant(
                AssistantTurn(
                    text="A" * 60,
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ),
        ],
        todos=[],
        audit_entries=[],
        token_usage=[],
    )

    forked = store.fork(source)

    assert forked.id != source.id
    assert forked.title == "Original Work (fork)"

    source_loaded = store.load(source.id)
    fork_loaded = store.load(forked.id)
    assert source_loaded.messages == fork_loaded.messages

    source_blob_ref = source_loaded.messages[1]["content_ref"]
    fork_blob_ref = fork_loaded.messages[1]["content_ref"]
    assert source_blob_ref == fork_blob_ref
    assert store.read_blob(source.id, source_blob_ref) == "A" * 60
    assert store.read_blob(forked.id, fork_blob_ref) == "A" * 60
    assert store.blob_path(source.id, source_blob_ref) != store.blob_path(forked.id, fork_blob_ref)


def test_ch30_fork_with_custom_title_restores_same_runtime_state(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions", blob_threshold_chars=20)
    source = store.create(cwd=tmp_path, title="Parent Session")
    source = store.save_runtime(
        source,
        messages=[
            Message.user("Inspect auth."),
            Message.assistant(
                AssistantTurn(
                    text="Need more detail.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ),
        ],
        todos=[],
        audit_entries=[],
        token_usage=[],
    )

    forked = store.fork(source, title="Auth Investigation Branch")
    agent = HarnessAgent(MockStreamProvider(deque()))
    restored = store.restore_into_agent(agent, store.load(forked.id))

    assert forked.title == "Auth Investigation Branch"
    assert [message.kind for message in restored] == ["user", "assistant"]
    assert restored[0].content == "Inspect auth."
    assert restored[1].turn is not None
    assert restored[1].turn.text == "Need more detail."
