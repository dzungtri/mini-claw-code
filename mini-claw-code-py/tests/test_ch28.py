from mini_claw_code_py import (
    AgentApprovalUpdate,
    AgentSubagentUpdate,
    AgentTodoUpdate,
    AgentTokenUsage,
    render_runtime_status,
    render_surface_block,
    surface_block_for_event,
)


def test_ch28_surface_block_for_todo_event_renders_summary_and_details() -> None:
    event = AgentTodoUpdate(
        message="Todo list updated:\nTodo list:\n- [x] Inspect\n- [>] Edit",
        total=2,
        completed=1,
    )

    block = surface_block_for_event(event)

    assert block is not None
    assert block.kind == "todo"
    assert block.summary == "1/2 completed"
    assert render_surface_block(block) == [
        "[todo] 1/2 completed",
        "Todo list:",
        "- [x] Inspect",
        "- [>] Edit",
    ]


def test_ch28_surface_block_for_subagent_and_approval_events_is_concise() -> None:
    subagent_block = surface_block_for_event(
        AgentSubagentUpdate(
            message="Subagent started (1/2): inspect auth",
            status="started",
            index=1,
            total=2,
            brief="inspect auth",
        )
    )
    approval_block = surface_block_for_event(
        AgentApprovalUpdate(
            message="Approval required: Overwrite existing file `a.py`?",
            status="required",
            tool_name="write",
        )
    )

    assert render_surface_block(subagent_block) == ["[subagent] started 1/2: inspect auth"]
    assert render_surface_block(approval_block) == [
        "[approval] required for write",
        "Approval required: Overwrite existing file `a.py`?",
    ]


def test_ch28_runtime_status_renders_mode_profile_todos_and_usage() -> None:
    lines = render_runtime_status(
        mode="execution",
        control_profile="balanced",
        todo_text="Todo list:\n- [>] Edit implementation",
        token_usage_text="Token usage: 2 turn(s), prompt~100, completion~20, total~120",
    )

    assert lines == [
        "Mode: execution",
        "Control profile: balanced",
        "Todo list:",
        "- [>] Edit implementation",
        "Token usage: 2 turn(s), prompt~100, completion~20, total~120",
    ]


def test_ch28_surface_block_for_usage_event_strips_prefix() -> None:
    block = surface_block_for_event(
        AgentTokenUsage("Token usage: turn 2, prompt~940, completion~83, total~1023, session~1841")
    )

    assert render_surface_block(block) == [
        "[usage] turn 2, prompt~940, completion~83, total~1023, session~1841"
    ]
