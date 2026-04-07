from __future__ import annotations

from typing import Any, Sequence

from ..types import AssistantTurn, Message, Provider, ToolDefinition


class OpenRouterProvider(Provider):
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = self.OPENROUTER_BASE_URL

    @classmethod
    def new(cls, api_key: str, model: str) -> "OpenRouterProvider":
        raise NotImplementedError("Store api_key, model, and the default base URL")

    def with_base_url(self, url: str) -> "OpenRouterProvider":
        raise NotImplementedError("Override the base URL and return self")

    @classmethod
    def from_env_with_model(cls, model: str) -> "OpenRouterProvider":
        raise NotImplementedError(
            "Read OPENROUTER_API_KEY from the environment and build a provider"
        )

    @classmethod
    def from_env(cls) -> "OpenRouterProvider":
        raise NotImplementedError("Call from_env_with_model using the default model")

    @staticmethod
    def convert_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
        raise NotImplementedError("Map Message values to OpenAI-compatible API messages")

    @staticmethod
    def convert_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
        raise NotImplementedError("Map ToolDefinition values to OpenAI-compatible API tools")

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> AssistantTurn:
        raise NotImplementedError(
            "Build the request body, POST it to /chat/completions, and parse the response"
        )
