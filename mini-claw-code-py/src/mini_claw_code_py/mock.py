from __future__ import annotations

from collections import deque
from typing import Sequence

from .types import AssistantTurn, Message, Provider, ToolDefinition


class MockProvider(Provider):
    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self._responses = responses

    async def chat(
        self,
        _messages: Sequence[Message],
        _tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        if not self._responses:
            raise RuntimeError("MockProvider: no more responses")
        return self._responses.popleft()
