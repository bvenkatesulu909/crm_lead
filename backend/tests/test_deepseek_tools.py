"""DeepSeek tool calling (ADR 0013, step PC1 / ticket CRM-104), with a fake HTTP client.

The rest of the CRM speaks one tool format (Anthropic-style: tool definitions with
``input_schema``, ``tool_use`` and ``tool_result`` blocks). DeepSeek's API is OpenAI-compatible,
so ``DeepSeekChatModel`` translates both ways. No key and no network: the HTTP call is a fake
that records what would have been sent and answers with a scripted response.
"""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.assistant.llm import (
    AssistantUnavailableError,
    DeepSeekChatModel,
    ModelReply,
    ToolUse,
)
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL

SAVE_LEAD = {
    "name": "save_lead",
    "description": "Save the visitor's details as a lead.",
    "input_schema": {
        "type": "object",
        "properties": {"full_name": {"type": "string"}, "phone": {"type": "string"}},
        "required": ["full_name", "phone"],
    },
}


class FakeHttp:
    """Stands in for httpx.post: records requests, returns scripted JSON (or raises)."""

    def __init__(self, *answers: dict[str, Any] | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append({"url": url, **kwargs})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer, request=httpx.Request("POST", url))


def model(http: FakeHttp) -> DeepSeekChatModel:
    settings = Settings(
        _env_file=None,
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        ai_provider="deepseek",
        deepseek_api_key=SecretStr("test-key-not-real"),
        deepseek_model="deepseek-chat",
    )
    return DeepSeekChatModel(settings, http_post=http)


def text_answer(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    }


def tool_answer(*calls: tuple[str, str, str], text: str | None = None) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {"id": cid, "type": "function", "function": {"name": n, "arguments": a}}
                        for cid, n, a in calls
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 40, "completion_tokens": 9},
    }


def test_tools_are_sent_in_openai_format() -> None:
    http = FakeHttp(text_answer("Hello! What is your name?"))
    reply = model(http).reply(
        system="You are the concierge.",
        messages=[{"role": "user", "content": "Hi"}],
        tools=[SAVE_LEAD],
    )
    sent = http.requests[0]["json"]
    assert sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "save_lead",
                "description": "Save the visitor's details as a lead.",
                "parameters": SAVE_LEAD["input_schema"],
            },
        }
    ]
    assert sent["messages"][0] == {"role": "system", "content": "You are the concierge."}
    assert sent["messages"][1] == {"role": "user", "content": "Hi"}
    assert reply == ModelReply(
        "Hello! What is your name?", [], "end_turn", {"input_tokens": 12, "output_tokens": 5}
    )


def test_a_tool_call_becomes_a_tool_use() -> None:
    http = FakeHttp(
        tool_answer(("call_1", "save_lead", '{"full_name": "Suresh", "phone": "9848012345"}'))
    )
    reply = model(http).reply(
        system="s", messages=[{"role": "user", "content": "x"}], tools=[SAVE_LEAD]
    )
    assert reply.tool_uses == [
        ToolUse("call_1", "save_lead", {"full_name": "Suresh", "phone": "9848012345"})
    ]
    assert reply.stop_reason == "tool_use"
    assert reply.text == ""
    assert reply.usage == {"input_tokens": 40, "output_tokens": 9}
    # The reply can be sent back as an assistant turn in our own (Anthropic-style) format.
    assert reply.as_content() == [
        {"type": "tool_use", "id": "call_1", "name": "save_lead",
         "input": {"full_name": "Suresh", "phone": "9848012345"}},
    ]  # fmt: skip


def test_several_tool_calls_and_text_in_one_answer() -> None:
    http = FakeHttp(
        tool_answer(("a", "save_lead", "{}"), ("b", "save_lead", '{"phone": "1"}'), text="Saving.")
    )
    reply = model(http).reply(
        system="s", messages=[{"role": "user", "content": "x"}], tools=[SAVE_LEAD]
    )
    assert reply.text == "Saving."
    assert [(t.id, t.input) for t in reply.tool_uses] == [("a", {}), ("b", {"phone": "1"})]


@pytest.mark.parametrize("arguments", ["not json", "[1, 2]", '"a string"', ""])
def test_broken_arguments_reach_the_tool_as_an_empty_input(arguments: str) -> None:
    # The tool's own validation then refuses it and tells the model - nothing is guessed.
    http = FakeHttp(tool_answer(("c", "save_lead", arguments)))
    reply = model(http).reply(
        system="s", messages=[{"role": "user", "content": "x"}], tools=[SAVE_LEAD]
    )
    assert reply.tool_uses == [ToolUse("c", "save_lead", {})]


def test_the_tool_round_trip_is_translated_back() -> None:
    """Our history after one tool round, as the assistant service builds it, in DeepSeek's form."""
    http = FakeHttp(text_answer("Thank you, Suresh! An advisor will call you."))
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "I am Suresh, 9848012345"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me save that."},
                {"type": "tool_use", "id": "call_1", "name": "save_lead",
                 "input": {"full_name": "Suresh", "phone": "9848012345"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1",
                 "content": '{"saved": true}', "is_error": False},
            ],
        },
    ]  # fmt: skip
    reply = model(http).reply(system="s", messages=history, tools=[SAVE_LEAD])
    sent = http.requests[0]["json"]["messages"]
    assert sent[1] == {"role": "user", "content": "I am Suresh, 9848012345"}
    assert sent[2] == {
        "role": "assistant",
        "content": "Let me save that.",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "save_lead",
                    "arguments": json.dumps({"full_name": "Suresh", "phone": "9848012345"}),
                },
            }
        ],
    }
    assert sent[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"saved": true}'}
    assert reply.text == "Thank you, Suresh! An advisor will call you."


def test_a_failed_tool_is_marked_for_the_model() -> None:
    http = FakeHttp(text_answer("Could you give me your phone number?"))
    history: list[dict[str, Any]] = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "x", "name": "save_lead", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x",
             "content": "phone is required", "is_error": True},
        ]},
    ]  # fmt: skip
    model(http).reply(system="s", messages=history, tools=[SAVE_LEAD])
    sent = http.requests[0]["json"]["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": None,  # a tool-only turn has no text
        "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "save_lead", "arguments": "{}"}}
        ],
    }
    assert sent[2] == {"role": "tool", "tool_call_id": "x", "content": "Error: phone is required"}


def test_without_tools_the_request_is_unchanged() -> None:
    """The knowledge answers call DeepSeek with tools=[]: no tools key, plain messages."""
    http = FakeHttp(text_answer("The return policy is 30 days."))
    reply = model(http).reply(
        system="s",
        messages=[{"role": "user", "content": [{"type": "text", "text": "Policy?"}]}],
        tools=[],
    )
    sent = http.requests[0]["json"]
    assert "tools" not in sent
    assert sent["messages"][1] == {"role": "user", "content": "Policy?"}
    assert sent["temperature"] == 0
    assert http.requests[0]["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert http.requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert reply.text == "The return policy is 30 days."


def test_a_provider_failure_becomes_a_clean_503() -> None:
    http = FakeHttp(httpx.ConnectTimeout("timed out"))
    with pytest.raises(AssistantUnavailableError):
        model(http).reply(
            system="s", messages=[{"role": "user", "content": "x"}], tools=[SAVE_LEAD]
        )


def test_an_unexpected_answer_shape_gives_an_empty_reply_not_a_crash() -> None:
    http = FakeHttp({"choices": []})
    reply = model(http).reply(
        system="s", messages=[{"role": "user", "content": "x"}], tools=[SAVE_LEAD]
    )
    assert reply.text == "" and reply.tool_uses == []
