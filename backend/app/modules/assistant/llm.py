"""The language model behind the assistant, behind a small interface.

``ChatModel`` is a Protocol: production uses Claude through the official Anthropic SDK, tests
use a scripted fake. The rest of the module never imports the SDK, so the security rules can be
tested without calling (or paying for) a real model.
"""

import json
import logging
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.observability.metrics import observe_ai_call

logger = logging.getLogger(__name__)

# What DeepSeekChatModel calls to send a request: httpx.post, or a fake in tests.
HttpPost = Callable[..., Any]
# What DeepSeekChatModel calls to STREAM a request: opens it and gives the response's lines.
HttpStream = Callable[..., AbstractContextManager[Iterator[str]]]


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


# A streamed reply: the answer's text piece by piece, then (as the generator's return value) the
# complete reply with its tool calls and token counts. Use it as ``reply = yield from ...``.
TextStream = Generator[str, None, ModelReply]


def stream_reply(
    model: ChatModel,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> TextStream:
    """Ask ``model`` and get its text as it is written (ADR 0023, step VM1).

    A model that can stream (it has ``stream_reply``) sends its pieces as they come; any other
    model answers in one piece. Either way the caller ends up with the same ``ModelReply``."""
    streaming = getattr(model, "stream_reply", None)
    if callable(streaming):
        streamed: ModelReply = yield from streaming(system=system, messages=messages, tools=tools)
        return streamed
    reply = model.reply(system=system, messages=messages, tools=tools)
    if reply.text:
        yield reply.text
    return reply


def _unavailable() -> "AssistantUnavailableError":
    return AssistantUnavailableError(
        "The assistant is temporarily unavailable. Please try again or open a ticket."
    )


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
            raise self._failed(exc, started) from exc
        return self._finished(response, started)

    def stream_reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> TextStream:
        """The same call, streamed: text pieces first, then the full reply."""
        started = time.perf_counter()
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
            ) as stream:
                yield from stream.text_stream
                response = stream.get_final_message()
        except self._anthropic.APIError as exc:
            raise self._failed(exc, started) from exc
        return self._finished(response, started)

    def _failed(self, exc: Exception, started: float) -> "AssistantUnavailableError":
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
        return _unavailable()

    def _finished(self, response: Any, started: float) -> ModelReply:
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

    The rest of the CRM speaks one tool format (Anthropic-style: definitions with
    ``input_schema``, ``tool_use`` and ``tool_result`` blocks). This class translates both ways
    (ADR 0013): tools go out as OpenAI "function" tools, ``tool_calls`` come back as ``ToolUse``,
    and tool results go back as ``role: "tool"`` messages. Arguments that aren't a JSON object
    reach the tool as ``{}``, whose own validation then refuses them - nothing is guessed.

    ``http_post`` is ``httpx.post`` unless a test passes a fake (no key or network needed).
    """

    available = True
    provider = "deepseek"

    def __init__(
        self,
        settings: Settings,
        http_post: HttpPost | None = None,
        http_stream: HttpStream | None = None,
    ) -> None:
        if settings.deepseek_api_key is None:
            raise ValueError("deepseek_api_key is not configured")
        self._api_key = settings.deepseek_api_key.get_secret_value()
        self._base_url = settings.deepseek_base_url.rstrip("/")
        self._model = settings.deepseek_model
        self._fallbacks = settings.deepseek_fallback_model_list
        self._timeout = settings.assistant_timeout_seconds
        self._max_tokens = settings.assistant_max_tokens
        self._input_price = settings.ai_input_price_per_million
        self._output_price = settings.ai_output_price_per_million
        self._post = http_post
        self._stream = http_stream

    def _payload(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *_openai_messages(messages)],
            "max_tokens": self._max_tokens,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = [_openai_tool(t) for t in tools]
        if self._fallbacks:
            # OpenRouter tries these in order when the first model fails or is rate-limited.
            payload["models"] = [self._model, *self._fallbacks]
        return payload

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _failed(self, exc: Exception, started: float) -> "AssistantUnavailableError":
        observe_ai_call(
            provider="deepseek",
            model=self._model,
            outcome="timeout" if "Timeout" in type(exc).__name__ else "error",
            seconds=time.perf_counter() - started,
            input_price_per_million=self._input_price,
            output_price_per_million=self._output_price,
        )
        logger.warning("DeepSeek call failed", extra={"error": type(exc).__name__})
        return _unavailable()

    def _observed(self, started: float, input_tokens: int, output_tokens: int) -> None:
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

    def stream_reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> TextStream:
        """The same call with ``stream: true``: text pieces as they come, then the full reply.

        The OpenAI-compatible stream sends lines ``data: {json}`` (OpenRouter also sends comment
        lines starting with ":", ignored) and ends with ``data: [DONE]``. Tool calls arrive in
        pieces keyed by ``index`` and are put together here; the token counts come in the last
        chunk because ``stream_options.include_usage`` is asked for."""
        payload = self._payload(system, messages, tools)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        started = time.perf_counter()
        texts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        try:
            opener = self._stream or _httpx_stream
            with opener(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
                timeout=self._timeout,
            ) as lines:
                for line in lines:
                    chunk = _stream_chunk(line)
                    if chunk is None:
                        continue
                    if chunk.get("error"):
                        raise RuntimeError("provider error in stream")
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    piece = _delta(chunk, calls)
                    if piece:
                        texts.append(piece)
                        yield piece
        except Exception as exc:  # noqa: BLE001 - provider errors must become a clean 503
            raise self._failed(exc, started) from exc
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        self._observed(started, input_tokens, output_tokens)
        tool_uses = _tool_uses(
            {
                "tool_calls": [
                    {
                        "id": call.get("id", f"call-{index}"),
                        "function": {"name": call.get("name", ""), "arguments": call["arguments"]},
                    }
                    for index, call in sorted(calls.items())
                ]
            }
        )
        return ModelReply(
            "".join(texts).strip(),
            tool_uses,
            "tool_use" if tool_uses else "end_turn",
            {"input_tokens": input_tokens, "output_tokens": output_tokens},
        )

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        payload = self._payload(system, messages, tools)
        started = time.perf_counter()
        try:
            post = self._post
            if post is None:
                import httpx

                post = httpx.post
            response = post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - provider errors must become a clean 503
            raise self._failed(exc, started) from exc

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        self._observed(started, input_tokens, output_tokens)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            message = {}
        text = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
        tool_uses = _tool_uses(message)
        return ModelReply(
            text,
            tool_uses,
            "tool_use" if tool_uses else "end_turn",
            {"input_tokens": input_tokens, "output_tokens": output_tokens},
        )


@contextmanager
def _httpx_stream(url: str, **kwargs: Any) -> Iterator[Iterator[str]]:
    import httpx

    with httpx.stream("POST", url, **kwargs) as response:
        response.raise_for_status()
        yield response.iter_lines()


def _stream_chunk(line: str) -> dict[str, Any] | None:
    """One ``data: {json}`` line of a stream as a dict; None for anything else."""
    line = line.strip()
    if not line.startswith("data:"):
        return None  # empty lines and ": keep-alive" comments
    body = line[5:].strip()
    if not body or body == "[DONE]":
        return None
    try:
        chunk = json.loads(body)
    except ValueError:
        return None
    return chunk if isinstance(chunk, dict) else None


def _delta(chunk: dict[str, Any], calls: dict[int, dict[str, str]]) -> str:
    """The text piece of one chunk; tool-call pieces are added to ``calls``."""
    try:
        delta = chunk["choices"][0]["delta"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(delta, dict):
        return ""
    for part in delta.get("tool_calls") or []:
        if not isinstance(part, dict):
            continue
        index = part.get("index", 0)
        call = calls.setdefault(index if isinstance(index, int) else 0, {"arguments": ""})
        if part.get("id"):
            call["id"] = str(part["id"])
        function = part.get("function") or {}
        if isinstance(function, dict):
            if function.get("name"):
                call["name"] = str(function["name"])
            if function.get("arguments"):
                call["arguments"] += str(function["arguments"])
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _text_of(blocks: list[Any]) -> str:
    return "\n".join(
        str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    )


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Our (Anthropic-style) history as OpenAI-style messages.

    - plain text stays a plain message;
    - an assistant turn with ``tool_use`` blocks becomes one message with ``tool_calls``
      (``content`` is None when the turn had no text);
    - a user turn with ``tool_result`` blocks becomes one ``role: "tool"`` message per result
      (a failed tool's content is prefixed with "Error: " so the model knows).
    """
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message["role"])
        content = message.get("content", "")
        if not isinstance(content, list):
            converted.append({"role": role, "content": str(content)})
            continue
        calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
        if role == "assistant" and calls:
            converted.append(
                {
                    "role": "assistant",
                    "content": _text_of(content) or None,
                    "tool_calls": [
                        {
                            "id": str(c["id"]),
                            "type": "function",
                            "function": {
                                "name": str(c["name"]),
                                "arguments": json.dumps(c.get("input") or {}),
                            },
                        }
                        for c in calls
                    ],
                }
            )
        elif results:
            for r in results:
                body = str(r.get("content", ""))
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(r["tool_use_id"]),
                        "content": f"Error: {body}" if r.get("is_error") else body,
                    }
                )
        else:
            converted.append({"role": role, "content": _text_of(content)})
    return converted


def _tool_uses(message: Any) -> list[ToolUse]:
    if not isinstance(message, dict):
        return []
    uses: list[ToolUse] = []
    for call in message.get("tool_calls") or []:
        try:
            function = call["function"]
            name, raw = str(function["name"]), function.get("arguments") or ""
            call_id = str(call["id"])
        except (KeyError, TypeError):
            continue
        try:
            arguments = json.loads(raw)
        except (TypeError, ValueError):
            arguments = None
        uses.append(ToolUse(call_id, name, arguments if isinstance(arguments, dict) else {}))
    return uses


class UnconfiguredChatModel:
    available = False

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        raise AssistantUnavailableError("The assistant is not configured (CRM_ANTHROPIC_API_KEY).")


def build_chat_model(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        from app.modules.assistant.fake_llm import FakeStaffModel  # tests and demos only

        return FakeStaffModel()
    if settings.ai_provider == "deepseek":
        if settings.deepseek_api_key is None:
            return UnconfiguredChatModel()
        return DeepSeekChatModel(settings)
    if settings.anthropic_api_key is None:
        return UnconfiguredChatModel()
    return ClaudeChatModel(settings)
