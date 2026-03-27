import asyncio
from collections import deque

import pytest

from mini_claw_code_py import AgentTokenUsage, HarnessAgent, Message, MockStreamProvider, StopReason
from mini_claw_code_py.types import AssistantTurn


@pytest.mark.asyncio
async def test_ch26_token_usage_tracing_emits_runtime_event() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="Hello from the harness.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                )
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_token_usage_tracing()
    queue: asyncio.Queue[object] = asyncio.Queue()

    result = await agent.execute([Message.user("Say hello")], queue)

    assert result == "Hello from the harness."
    usage_events: list[AgentTokenUsage] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentTokenUsage):
            usage_events.append(event)
    assert len(usage_events) == 1
    assert usage_events[0].message.startswith("Token usage: turn 1, ")
    assert agent.token_usage_tracker().total_tokens() > 0


@pytest.mark.asyncio
async def test_ch26_token_usage_tracker_accumulates_across_turns() -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text="First reply.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
                AssistantTurn(
                    text="Second reply.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = HarnessAgent(provider).enable_core_tools().enable_token_usage_tracing()

    queue1: asyncio.Queue[object] = asyncio.Queue()
    queue2: asyncio.Queue[object] = asyncio.Queue()

    await agent.execute([Message.user("First")], queue1)
    await agent.execute([Message.user("Second")], queue2)

    tracker = agent.token_usage_tracker()
    assert len(tracker.turns()) == 2
    assert tracker.total_prompt_tokens() > 0
    assert tracker.total_completion_tokens() > 0
    assert tracker.render().startswith("Token usage: 2 turn(s), ")
