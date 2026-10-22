"""The language model behind the assistant, behind a small interface.

``ChatModel`` is a Protocol: production uses Claude through the official Anthropic SDK, tests
use a scripted fake. The rest of the module never imports the SDK, so the security rules can be
tested without calling (or paying for) a real model.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.observability.metrics import observe_ai_call

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
    usage: dict[str, int] = field(default_factory=dict)

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
        self._input_price = settings.ai_input_price_per_million
        self._output_price = settings.ai_output_price_per_million

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        started = time.perf_counter()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
            )
        except self._anthropic.APIError as exc:
            observe_ai_call(
                provider="anthropic",
                model=self._model,
                outcome="timeout" if "Timeout" in type(exc).__name__ else "error",
                seconds=time.perf_counter() - started,
                input_price_per_million=self._input_price,
                output_price_per_million=self._output_price,
            )
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
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        observe_ai_call(
            provider="anthropic",
            model=self._model,
            outcome="ok",
            seconds=time.perf_counter() - started,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_per_million=self._input_price,
            output_price_per_million=self._output_price,
        )
        return ModelReply(
            "\n".join(texts).strip(),
            tool_uses,
            str(response.stop_reason),
            {"input_tokens": input_tokens, "output_tokens": output_tokens},
        )


class DeepSeekChatModel:
    """DeepSeek's OpenAI-compatible chat endpoint, behind the same ChatModel interface.

    Tool calling is deliberately not translated yet: the grounded knowledge answer path uses
    tools=[], while the portal assistant still runs on Anthropic. Selecting DeepSeek for a
    tool-using call fails closed instead of silently changing tool semantics.
    """

    available = True
    provider = "deepseek"

    def __init__(self, settings: Settings) -> None:
        if settings.deepseek_api_key is None:
            raise ValueError("deepseek_api_key is not configured")
        self._api_key = settings.deepseek_api_key.get_secret_value()
        self._base_url = settings.deepseek_base_url.rstrip("/")
        self._model = settings.deepseek_model
        self._timeout = settings.assistant_timeout_seconds
        self._max_tokens = settings.assistant_max_tokens
        self._input_price = settings.ai_input_price_per_million
        self._output_price = settings.ai_output_price_per_million

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        if tools:
            raise AssistantUnavailableError(
                "DeepSeek tool calling is not enabled; use the Anthropic provider for tools."
            )
        normalized: list[dict[str, str]] = []
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            normalized.append({"role": str(message["role"]), "content": str(content)})

        started = time.perf_counter()
        try:
            import httpx

            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "system", "content": system}, *normalized],
                    "max_tokens": self._max_tokens,
                    "temperature": 0,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - provider errors must become a clean 503
            observe_ai_call(
                provider="deepseek",
                model=self._model,
                outcome="timeout" if "Timeout" in type(exc).__name__ else "error",
                seconds=time.perf_counter() - started,
                input_price_per_million=self._input_price,
                output_price_per_million=self._output_price,
            )
            logger.warning("DeepSeek call failed", extra={"error": type(exc).__name__})
            raise AssistantUnavailableError(
                "The assistant is temporarily unavailable. Please try again or open a ticket."
            ) from exc

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        observe_ai_call(
            provider="deepseek",
            model=self._model,
            outcome="ok",
            seconds=time.perf_counter() - started,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_per_million=self._input_price,
            output_price_per_million=self._output_price,
        )
        text = ""
        try:
            text = str(data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            text = ""
        return ModelReply(
            text,
            [],
            "end_turn",
            {"input_tokens": input_tokens, "output_tokens": output_tokens},
        )


class UnconfiguredChatModel:
    available = False

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        raise AssistantUnavailableError("The assistant is not configured (CRM_ANTHROPIC_API_KEY).")


def build_chat_model(settings: Settings) -> ChatModel:
    if settings.ai_provider == "deepseek":
        if settings.deepseek_api_key is None:
            return UnconfiguredChatModel()
        return DeepSeekChatModel(settings)
    if settings.anthropic_api_key is None:
        return UnconfiguredChatModel()
    return ClaudeChatModel(settings)
