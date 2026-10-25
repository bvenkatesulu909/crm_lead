"""The fake staff assistant model (ADR 0014, step AP5): for tests and local demos only.

It needs no key. It understands one sentence - "mark lead <id> as contacted because ..." - and
answers with a propose_lead_status tool call; everything else gets a short help text. It can
never run in production.
"""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.assistant.fake_llm import FakeStaffModel
from app.modules.assistant.llm import build_chat_model
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL

LEAD = str(uuid.uuid4())


def ask(question: str, *followups: dict[str, Any]) -> Any:
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}, *followups]
    return FakeStaffModel().reply(system="s", messages=messages, tools=[])


def settings(**values: Any) -> Settings:
    values.setdefault("oidc_issuer", TEST_ISSUER)
    return Settings(_env_file=None, database_url=UNREACHABLE_DATABASE_URL, **values)


def test_it_proposes_a_status_change_with_the_reason_from_the_question() -> None:
    reply = ask(f"Please mark lead {LEAD} as contacted because the buyer answered my call.")
    [use] = reply.tool_uses
    assert use.name == "propose_lead_status"
    assert use.input == {
        "lead_id": LEAD,
        "status": "contacted",
        "reason": "the buyer answered my call.",
    }


@pytest.mark.parametrize("status", ["contacted", "qualified", "unqualified"])
def test_every_allowed_status_is_understood(status: str) -> None:
    [use] = ask(f"mark lead {LEAD} as {status}").tool_uses
    assert use.input["status"] == status
    assert use.input["reason"]  # a default reason when none was given


@pytest.mark.parametrize(
    "question",
    [
        "How are you?",
        f"mark lead {LEAD} as converted",  # never through the assistant
        "mark lead not-an-id as contacted",
        f"delete lead {LEAD}",
    ],
)
def test_anything_else_gets_a_help_text_and_no_tool_call(question: str) -> None:
    reply = ask(question)
    assert reply.tool_uses == []
    assert "mark lead" in reply.text.lower()


def test_after_the_tool_ran_it_says_the_proposal_is_waiting() -> None:
    ok = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "{}", "is_error": False}
        ],
    }
    reply = ask("x", {"role": "assistant", "content": []}, ok)
    assert reply.tool_uses == []
    assert "waiting" in reply.text.lower() and "nothing has changed" in reply.text.lower()


def test_after_a_refused_tool_call_it_says_so() -> None:
    bad = {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t", "content": "{}", "is_error": True}],
    }
    reply = ask("x", {"role": "assistant", "content": []}, bad)
    assert reply.tool_uses == []
    assert "could not" in reply.text.lower()


def test_the_provider_setting_builds_it_and_production_refuses_it() -> None:
    model = build_chat_model(settings(ai_provider="fake"))
    assert isinstance(model, FakeStaffModel) and model.available
    with pytest.raises(ValidationError, match="fake"):
        settings(
            ai_provider="fake",
            environment="production",
            oidc_issuer="https://auth.example.test/realms/crm",
            files_s3_secure=True,
        )
