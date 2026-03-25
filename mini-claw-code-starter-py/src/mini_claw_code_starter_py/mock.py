from __future__ import annotations

from collections import deque
from typing import Sequence

from .types import AssistantTurn, Message, Provider, ToolDefinition


class MockProvider(Provider):
    """Chapter 1: implement a canned provider backed by a deque."""

    def __init__(self, responses: deque[AssistantTurn]) -> None:
        self.responses = responses

    @classmethod
    def new(cls, responses: deque[AssistantTurn]) -> "MockProvider":
        raise NotImplementedError("Wrap the response deque in a MockProvider and return it")

    async def chat(
        self,
        _messages: Sequence[Message],
        _tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        raise NotImplementedError("Pop the next response from the left or raise if empty")
