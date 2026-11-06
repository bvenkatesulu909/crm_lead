"""Streaming from the OpenAI-compatible API (DeepSeek / OpenRouter), ADR 0023 step VM1.

No key and no network: the stream is a fake that hands back scripted ``data:`` lines, the way
``httpx.stream`` would.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.assistant.llm import (
    AssistantUnavailableError,
    DeepSeekChatModel,
    ModelReply,
    stream_reply,
)
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL


def data(chunk: dict[str, Any]) -> str:
    return "data: " + json.dumps(chunk)


def text_chunk(text: str) -> str:
    return data({"choices": [{"delta": {"content": text}}]})


class FakeStream:
    def __init__(self, lines: list[str], fail_after: int | None = None) -> None:
        self.lines = lines
        self.fail_after = fail_after
        self.requests: list[dict[str, Any]] = []

    @contextmanager
    def __call__(self, url: str, **kwargs: Any) -> Iterator[Iterator[str]]:
        self.requests.append({"url": url, **kwargs})

        def lines() -> Iterator[str]:
            for index, line in enumerate(self.lines):
                if self.fail_after is not None and index == self.fail_after:
                    raise ConnectionError("network went away")
                yield line

        yield lines()


def model(stream: FakeStream, **overrides: Any) -> DeepSeekChatModel:
    settings = Settings(
        _env_file=None,
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        ai_provider="deepseek",
        deepseek_api_key=SecretStr("test-key-not-real"),
        deepseek_model="deepseek-chat",
        **overrides,
    )
    return DeepSeekChatModel(settings, http_stream=stream)


def play(chat: Any) -> tuple[list[str], ModelReply]:
    pieces: list[str] = []
    gen = stream_reply(chat, system="sys", messages=[{"role": "user", "content": "hi"}], tools=[])
    while True:
        try:
            pieces.append(next(gen))
        except StopIteration as done:
            return pieces, done.value


def test_text_comes_piece_by_piece_and_the_reply_has_the_tokens() -> None:
    stream = FakeStream(
        [
            ": OPENROUTER PROCESSING",
            "",
            text_chunk("Your ticket "),
            text_chunk("is open."),
            data(
                {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
            ),
            "data: [DONE]",
        ]
    )
    pieces, reply = play(model(stream))
    assert pieces == ["Your ticket ", "is open."]
    assert reply.text == "Your ticket is open."
    assert reply.tool_uses == []
    assert reply.usage == {"input_tokens": 12, "output_tokens": 5}


def test_the_request_asks_for_a_stream_with_token_counts_and_keeps_the_fallbacks() -> None:
    stream = FakeStream([text_chunk("ok"), "data: [DONE]"])
    play(model(stream, deepseek_fallback_models="a/b:free,c/d:free"))
    body = stream.requests[0]["json"]
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["models"] == ["deepseek-chat", "a/b:free", "c/d:free"]
    assert stream.requests[0]["headers"]["Authorization"] == "Bearer test-key-not-real"


def test_a_tool_call_sent_in_pieces_is_put_together() -> None:
    def call(**delta: Any) -> str:
        return data({"choices": [{"delta": {"tool_calls": [delta]}}]})

    stream = FakeStream(
        [
            call(index=0, id="call_1", function={"name": "search_leads", "arguments": ""}),
            call(index=0, function={"arguments": '{"q": "As'}),
            call(index=0, function={"arguments": 'ha"}'}),
            call(index=1, id="call_2", function={"name": "get_ticket", "arguments": "{bad"}),
            "data: [DONE]",
        ]
    )
    pieces, reply = play(model(stream))
    assert pieces == []
    assert [(u.id, u.name, u.input) for u in reply.tool_uses] == [
        ("call_1", "search_leads", {"q": "Asha"}),
        ("call_2", "get_ticket", {}),  # broken arguments reach the tool as {} (it refuses)
    ]
    assert reply.stop_reason == "tool_use"


def test_a_network_failure_mid_stream_is_a_clean_503() -> None:
    stream = FakeStream([text_chunk("Half "), text_chunk("an answer")], fail_after=1)
    with pytest.raises(AssistantUnavailableError):
        play(model(stream))


def test_an_error_chunk_from_the_provider_is_a_clean_503() -> None:
    stream = FakeStream([data({"error": {"message": "rate limited", "code": 429}})])
    with pytest.raises(AssistantUnavailableError):
        play(model(stream))


def test_garbage_lines_are_ignored() -> None:
    stream = FakeStream(["data: not json", "event: ping", data({"choices": []}), text_chunk("Hi.")])
    pieces, reply = play(model(stream))
    assert pieces == ["Hi."]
    assert reply.text == "Hi."


def test_a_model_that_cannot_stream_answers_in_one_piece() -> None:
    class OnePiece:
        available = True

        def reply(self, **_: Any) -> ModelReply:
            return ModelReply("All at once.")

    pieces, reply = play(OnePiece())
    assert pieces == ["All at once."]
    assert reply.text == "All at once."
