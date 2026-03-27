from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .types import AssistantTurn, Message, ToolDefinition


@dataclass(slots=True)
class TokenUsageSnapshot:
    turn_index: int
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def notice(self, session_total_tokens: int) -> str:
        return (
            "Token usage: "
            f"turn {self.turn_index}, "
            f"prompt~{self.prompt_tokens}, "
            f"completion~{self.completion_tokens}, "
            f"total~{self.total_tokens}, "
            f"session~{session_total_tokens}"
        )


class TokenUsageTracker:
    def __init__(self) -> None:
        self._turns: list[TokenUsageSnapshot] = []

    def record(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> TokenUsageSnapshot:
        snapshot = TokenUsageSnapshot(
            turn_index=len(self._turns) + 1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._turns.append(snapshot)
        return snapshot

    def turns(self) -> list[TokenUsageSnapshot]:
        return list(self._turns)

    def total_prompt_tokens(self) -> int:
        return sum(turn.prompt_tokens for turn in self._turns)

    def total_completion_tokens(self) -> int:
        return sum(turn.completion_tokens for turn in self._turns)

    def total_tokens(self) -> int:
        return sum(turn.total_tokens for turn in self._turns)

    def render(self) -> str:
        if not self._turns:
            return "Token usage: no turns recorded yet."
        return (
            "Token usage: "
            f"{len(self._turns)} turn(s), "
            f"prompt~{self.total_prompt_tokens()}, "
            f"completion~{self.total_completion_tokens()}, "
            f"total~{self.total_tokens()}"
        )


def estimate_messages_tokens(messages: list[Message]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def estimate_message_tokens(message: Message) -> int:
    text_parts: list[str] = [message.kind]
    if message.content:
        text_parts.append(message.content)
    if message.turn is not None:
        text_parts.append(_assistant_turn_blob(message.turn))
    if message.tool_call_id:
        text_parts.append(message.tool_call_id)
    return estimate_text_tokens("\n".join(text_parts))


def estimate_tool_definitions_tokens(definitions: list[ToolDefinition]) -> int:
    if not definitions:
        return 0
    blobs: list[str] = []
    for definition in definitions:
        blobs.append(definition.name)
        blobs.append(definition.description)
        blobs.append(json.dumps(definition.parameters, sort_keys=True, ensure_ascii=True))
    return estimate_text_tokens("\n".join(blobs))


def estimate_assistant_turn_tokens(turn: AssistantTurn) -> int:
    return estimate_text_tokens(_assistant_turn_blob(turn))


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4) + 4)


def _assistant_turn_blob(turn: AssistantTurn) -> str:
    parts: list[str] = []
    if turn.text:
        parts.append(turn.text)
    for call in turn.tool_calls:
        parts.append(call.name)
        parts.append(json.dumps(call.arguments, sort_keys=True, ensure_ascii=True, default=str))
    return "\n".join(parts)
