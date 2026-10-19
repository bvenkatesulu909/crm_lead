"""The language model behind the assistant, behind a small interface.

``ChatModel`` is a Protocol: production uses Claude through the official Anthropic SDK, tests
use a scripted fake. The rest of the module never imports the SDK, so the security rules can be
tested without calling (or paying for) a real model.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings
from app.core.errors import DomainError

logger = logging.getLogger(__name__)


class AssistantUnavailableError(DomainError):
    status_code = 503
    code = "assistant_unavailable"


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    stop_reason: str = "end_turn"

    def as_content(self) -> list[dict[str, Any]]:
        """This reply as an assistant message, to send back together with tool results."""
        content: list[dict[str, Any]] = []
        if self.text:
            content.append({"type": "text", "text": self.text})
        content.extend(
            {"type": "tool_use", "id": t.id, "name": t.name, "input": t.input}
            for t in self.tool_uses
        )
        return content


class ChatModel(Protocol):
    available: bool

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply: ...


class ClaudeChatModel:
    available = True

    def __init__(self, settings: Settings) -> None:
        import anthropic  # imported here so tests and tooling don't need the SDK loaded

        if settings.anthropic_api_key is None:
            raise ValueError("anthropic_api_key is not configured")
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.assistant_timeout_seconds,
            max_retries=2,
            # User-level keys (sk-ant-usr) must name their workspace; workspace keys need nothing.
            default_headers=(
                {"anthropic-workspace-id": settings.anthropic_workspace_id}
                if settings.anthropic_workspace_id
                else None
            ),
        )
        self._model = settings.assistant_model
        self._max_tokens = settings.assistant_max_tokens

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
            )
        except self._anthropic.APIError as exc:
            # Never log the conversation itself - only what kind of failure it was.
            logger.warning("assistant model call failed", extra={"error": type(exc).__name__})
            raise AssistantUnavailableError(
                "The assistant is temporarily unavailable. Please try again or open a ticket."
            ) from exc
        texts: list[str] = []
        tool_uses: list[ToolUse] = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(ToolUse(block.id, block.name, dict(block.input)))
        return ModelReply("\n".join(texts).strip(), tool_uses, str(response.stop_reason))


class UnconfiguredChatModel:
    available = False

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        raise AssistantUnavailableError("The assistant is not configured (CRM_ANTHROPIC_API_KEY).")


def build_chat_model(settings: Settings) -> ChatModel:
    if settings.anthropic_api_key is None:
        return UnconfiguredChatModel()
    return ClaudeChatModel(settings)
