import asyncio
from collections import deque
from pathlib import Path
import json

import pytest

from mini_claw_code_py import (
    ARCHIVED_CONTEXT_OPEN,
    HarnessAgent,
    Message,
    MockStreamProvider,
    SessionStore,
    StopReason,
    TokenUsageTracker,
    ToolCall,
    create_session_id,
    derive_session_title,
    deserialize_messages,
    serialize_messages,
    strip_injected_system_prompt,
)
from mini_claw_code_py.control_plane import AuditLog
from mini_claw_code_py.todos import TodoBoard
from mini_claw_code_py.types import AssistantTurn


def test_ch29_session_store_saves_operational_snapshot_without_injected_prompt(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions", blob_threshold_chars=20)
    record = store.create(cwd=tmp_path)

    history = [
        Message.system("dynamic execution prompt"),
        Message.system(f"{ARCHIVED_CONTEXT_OPEN}\nOlder work\n</archived_context>"),
        Message.user("Write a long story about brave clocks."),
        Message.assistant(
            AssistantTurn(
                text="L" * 80,
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]

    todos = TodoBoard()
    todos.replace([{"content": "Draft story", "status": "in_progress"}])
    audit = AuditLog()
    audit.push("tool", "write: outputs/chapter_001.md")
    usage = TokenUsageTracker()
    usage.record(prompt_tokens=100, completion_tokens=40)

    saved = store.save_runtime(
        record,
        messages=history,
        todos=todos.items(),
        audit_entries=audit.entries(),
        token_usage=usage.turns(),
    )

    assert saved.title == "Write a long story about brave clocks."

    loaded = store.load(saved.id)
    assert [message["kind"] for message in loaded.messages] == ["system", "user", "assistant"]
    restored_messages = store.restore_into_agent(HarnessAgent(MockStreamProvider(deque())), loaded)
    assert restored_messages[0].content is not None
    assert restored_messages[0].content.startswith(ARCHIVED_CONTEXT_OPEN)
    assert restored_messages[1].content == "Write a long story about brave clocks."
    assert "content_ref" in loaded.messages[2]
    assert loaded.messages[2]["preview"] == "L" * 80

    blob_path = store.session_dir(saved.id) / loaded.messages[2]["content_ref"]
    assert blob_path.exists()
    assert "dynamic execution prompt" not in (store.session_dir(saved.id) / "session.json").read_text(encoding="utf-8")


def test_ch29_second_save_replaces_working_snapshot_and_cleans_old_blobs(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions", blob_threshold_chars=20)
    record = store.create(cwd=tmp_path)

    first_history = [
        Message.user("First task"),
        Message.assistant(
            AssistantTurn(
                text="A" * 60,
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]
    store.save_runtime(
        record,
        messages=first_history,
        todos=[],
        audit_entries=[],
        token_usage=[],
    )
    first_blob_names = sorted(path.name for path in (store.session_dir(record.id) / "blobs").iterdir())
    assert first_blob_names == ["msg_0001.txt"]

    second_history = [
        Message.user("Second task"),
        Message.assistant(
            AssistantTurn(
                text="short reply",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]
    store.save_runtime(
        record,
        messages=second_history,
        todos=[],
        audit_entries=[],
        token_usage=[],
    )

    session_dir = store.session_dir(record.id)
    assert list((session_dir / "blobs").iterdir()) == []

    loaded = store.load(record.id)
    restored = store.restore_into_agent(
        HarnessAgent(MockStreamProvider(deque())),
        loaded,
    )
    assert [message.content if message.content else message.turn.text for message in restored] == [
        "Second task",
        "short reply",
    ]


def test_ch29_restore_rebuilds_durable_runtime_state_into_fresh_agent(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions", blob_threshold_chars=50)
    record = store.create(cwd=tmp_path)

    history = [
        Message.user("Refine the parser."),
        Message.assistant(
            AssistantTurn(
                text="Parser updated.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]
    todos = TodoBoard()
    todos.replace(
        [
            {"content": "Inspect parser", "status": "completed"},
            {"content": "Refine parser", "status": "in_progress"},
        ]
    )
    audit = AuditLog()
    audit.push("verify", "Verification step observed via read")
    usage = TokenUsageTracker()
    usage.record(prompt_tokens=220, completion_tokens=30)

    store.save_runtime(
        record,
        messages=history,
        todos=todos.items(),
        audit_entries=audit.entries(),
        token_usage=usage.turns(),
    )

    agent = HarnessAgent(MockStreamProvider(deque()))
    loaded = store.load(record.id)
    restored_history = store.restore_into_agent(agent, loaded)

    assert [message.kind for message in restored_history] == ["user", "assistant"]
    assert agent.todo_board().render() == "Todo list:\n- [x] Inspect parser\n- [>] Refine parser"
    assert agent.audit_log().render() == "Audit log:\n- [verify] Verification step observed via read"
    assert agent.token_usage_tracker().render() == (
        "Token usage: 1 turn(s), prompt~220, completion~30, total~250"
    )


@pytest.mark.asyncio
async def test_ch29_resume_keeps_archived_context_when_fresh_system_prompt_is_rebuilt(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    record = store.create(cwd=tmp_path)
    record.messages = [
        {"kind": "system", "content": f"{ARCHIVED_CONTEXT_OPEN}\nOlder work\n</archived_context>"},
        {"kind": "user", "content": "Continue the task."},
    ]
    store.save_runtime(
        record,
        messages=[
            Message.system("dynamic prompt"),
            Message.system(f"{ARCHIVED_CONTEXT_OPEN}\nOlder work\n</archived_context>"),
            Message.user("Continue the task."),
        ],
        todos=[],
        audit_entries=[],
        token_usage=[],
    )

    agent = HarnessAgent(
        MockStreamProvider(
            deque(
                [
                    AssistantTurn(
                        text="Resumed.",
                        tool_calls=[],
                        stop_reason=StopReason.STOP,
                    )
                ]
            )
        )
    )
    history = store.restore_into_agent(agent, store.load(record.id))
    queue: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute(history, queue)

    assert history[0].kind == "system"
    assert history[1].kind == "system"
    assert history[1].content is not None
    assert history[1].content.startswith(ARCHIVED_CONTEXT_OPEN)


def test_ch29_strip_injected_system_prompt_preserves_archived_context_messages() -> None:
    messages = [
        Message.system("dynamic execution prompt"),
        Message.system(f"{ARCHIVED_CONTEXT_OPEN}\nOlder work\n</archived_context>"),
        Message.user("Continue."),
    ]

    stripped = strip_injected_system_prompt(messages)

    assert [message.kind for message in stripped] == ["system", "user"]
    assert stripped[0].content is not None
    assert stripped[0].content.startswith(ARCHIVED_CONTEXT_OPEN)


def test_ch29_derive_session_title_trims_quotes_truncates_and_falls_back() -> None:
    title = derive_session_title(
        [
            Message.system("prompt"),
            Message.user('   "Please build a very long and unusually descriptive plan for refactoring the parser and serializer modules together"   '),
        ]
    )
    fallback = derive_session_title([Message.system("prompt")])

    assert title == "Please build a very long and unusually descriptive plan for refactori..."
    assert fallback == "Untitled session"


def test_ch29_serialize_and_deserialize_round_trip_tool_results_and_tool_calls(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    (session_dir / "blobs").mkdir(parents=True)
    messages = [
        Message.user("Inspect parser."),
        Message.assistant(
            AssistantTurn(
                text="I will inspect it.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="read",
                        arguments={"path": "src/parser.py"},
                    )
                ],
                stop_reason=StopReason.TOOL_USE,
            )
        ),
        Message.tool_result("call_1", "parser content"),
        Message.assistant(
            AssistantTurn(
                text="Done.",
                tool_calls=[],
                stop_reason=StopReason.STOP,
            )
        ),
    ]

    serialized = serialize_messages(messages, session_dir=session_dir, blob_threshold_chars=1000)
    restored = deserialize_messages(serialized, session_dir=session_dir)

    assert [message.kind for message in restored] == ["user", "assistant", "tool_result", "assistant"]
    assert restored[1].turn is not None
    assert restored[1].turn.stop_reason is StopReason.TOOL_USE
    assert restored[1].turn.tool_calls[0].name == "read"
    assert restored[1].turn.tool_calls[0].arguments == {"path": "src/parser.py"}
    assert restored[2].tool_call_id == "call_1"
    assert restored[2].content == "parser content"


def test_ch29_list_recent_sorts_by_updated_at_and_respects_limit(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")

    older = store.create(cwd=tmp_path, title="Older")
    store.save_runtime(older, messages=[Message.user("old")], todos=[], audit_entries=[], token_usage=[])
    older_path = store.session_dir(older.id) / "session.json"
    older_raw = json.loads(older_path.read_text(encoding="utf-8"))
    older_raw["updated_at"] = "2026-03-27T10:00:00Z"
    older_path.write_text(json.dumps(older_raw, indent=2) + "\n", encoding="utf-8")

    newer = store.create(cwd=tmp_path, title="Newer")
    store.save_runtime(newer, messages=[Message.user("new")], todos=[], audit_entries=[], token_usage=[])
    newer_path = store.session_dir(newer.id) / "session.json"
    newer_raw = json.loads(newer_path.read_text(encoding="utf-8"))
    newer_raw["updated_at"] = "2026-03-27T11:00:00Z"
    newer_path.write_text(json.dumps(newer_raw, indent=2) + "\n", encoding="utf-8")

    recent = store.list_recent(limit=1)
    all_records = store.list_recent()

    assert len(recent) == 1
    assert recent[0].id == newer.id
    assert [record.id for record in all_records] == [newer.id, older.id]


def test_ch29_save_runtime_creates_session_layout_and_id_shape(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".mini-claw" / "sessions")
    record = store.create(cwd=tmp_path)
    store.save_runtime(
        record,
        messages=[Message.user("hello")],
        todos=[],
        audit_entries=[],
        token_usage=[],
    )

    session_dir = store.session_dir(record.id)

    assert record.id.startswith("sess_")
    assert len(record.id.split("_")) == 4
    assert (session_dir / "session.json").exists()
    assert (session_dir / "blobs").exists()
    assert (session_dir / "archive").exists()


def test_ch29_create_session_id_has_expected_prefix() -> None:
    session_id = create_session_id()

    assert session_id.startswith("sess_")
    assert len(session_id.split("_")) == 4
