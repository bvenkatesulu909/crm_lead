"""Public website chat (ADR 0013, step PC3): rules that need no database.

The save_lead tool's arguments, name splitting, the token and address hashes, the fake model
used in tests and demos, and the settings that keep the fake out of production.
"""

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.modules.public_chat import rules
from app.modules.public_chat.llm import FakeVisitorModel, build_public_chat_model
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL

GOOD = {"full_name": "Suresh Kumar", "phone": "+91 98480 12345"}


def settings(**values: Any) -> Settings:
    values.setdefault("oidc_issuer", TEST_ISSUER)
    return Settings(_env_file=None, database_url=UNREACHABLE_DATABASE_URL, **values)


# --- save_lead arguments ------------------------------------------------------------------------


def test_minimal_and_full_arguments_are_accepted() -> None:
    assert rules.SaveLeadArgs.model_validate(GOOD).phone == "+91 98480 12345"
    full = rules.SaveLeadArgs.model_validate(
        {
            **GOOD,
            "email": "suresh@example.test",
            "property_type": "villa",
            "budget_min_inr": 25_000_000,
            "budget_max_inr": 30_000_000,
            "location": "Gachibowli",
            "notes": "Wants a site visit on Sunday.",
        }
    )
    assert (full.property_type, full.budget_max_inr) == ("villa", 30_000_000)


@pytest.mark.parametrize(
    "changes",
    [
        {"full_name": "S"},  # too short
        {"full_name": None},
        {"phone": "call me"},
        {"phone": "123"},
        {"email": "not-an-address"},
        {"property_type": "castle"},
        {"budget_min_inr": -1},
        {"budget_min_inr": 1.5},
        {"budget_min_inr": 30_000_000, "budget_max_inr": 20_000_000},
        {"location": "x" * 161},
        {"notes": "x" * 1001},
        {"tenant_id": "00000000-0000-0000-0000-000000000001"},  # nothing extra from the model
        {"owner_id": "00000000-0000-0000-0000-000000000001"},
    ],
)
def test_bad_arguments_are_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        rules.SaveLeadArgs.model_validate({**GOOD, **changes})


@pytest.mark.parametrize(
    "full, expected",
    [
        ("Suresh Kumar", ("Suresh", "Kumar")),
        ("  Anil  Kumar  Reddy ", ("Anil Kumar", "Reddy")),
        ("Madonna", (None, "Madonna")),
    ],
)
def test_names_are_split_into_first_and_last(full: str, expected: tuple[str | None, str]) -> None:
    assert rules.split_name(full) == expected


def test_the_tool_definition_matches_the_arguments() -> None:
    tool = rules.SAVE_LEAD_TOOL
    assert tool["name"] == "save_lead"
    assert tool["input_schema"]["required"] == ["full_name", "phone"]
    assert set(tool["input_schema"]["properties"]) == set(rules.SaveLeadArgs.model_fields)


# --- tokens and addresses -------------------------------------------------------------------


def test_tokens_are_random_and_only_their_hash_is_kept() -> None:
    first, second = rules.new_token(), rules.new_token()
    assert first != second and len(first) >= 40
    assert rules.TOKEN_PATTERN.fullmatch(first)
    digest = rules.hash_token(first)
    assert len(digest) == 64 and first not in digest
    assert rules.hash_token(first) == digest  # stable, so the conversation can be found again


def test_visitor_addresses_are_hashed_with_the_server_key() -> None:
    a = rules.hash_ip("203.0.113.7", "k" * 40)
    assert a == rules.hash_ip("203.0.113.7", "k" * 40)
    assert a != rules.hash_ip("203.0.113.8", "k" * 40)
    assert a != rules.hash_ip("203.0.113.7", "z" * 40)  # without the key it can't be recomputed
    assert "203.0.113.7" not in a


# --- the fake model -------------------------------------------------------------------------


def _ask(model: FakeVisitorModel, *messages: dict[str, Any]) -> Any:
    return model.reply(system="s", messages=list(messages), tools=[rules.SAVE_LEAD_TOOL])


def test_the_fake_asks_for_details_until_it_gets_a_phone_number() -> None:
    reply = _ask(FakeVisitorModel(), {"role": "user", "content": "Hi, I want a flat"})
    assert reply.tool_uses == []
    assert "phone" in reply.text.lower()


def test_the_fake_saves_the_lead_once_it_has_a_phone_number() -> None:
    reply = _ask(
        FakeVisitorModel(),
        {"role": "user", "content": "I am Suresh Kumar, phone 98480 12345, 3BHK in Kokapet"},
    )
    [use] = reply.tool_uses
    assert use.name == "save_lead"
    args = rules.SaveLeadArgs.model_validate(use.input)  # always valid arguments
    assert (args.full_name, args.phone) == ("Suresh Kumar", "98480 12345")
    assert args.property_type == "apartment" and args.location == "Kokapet, Hyderabad"


def test_the_fake_thanks_the_visitor_after_the_tool_ran() -> None:
    result = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1",
         "content": '{"saved": true}', "is_error": False},
    ]}  # fmt: skip
    reply = _ask(FakeVisitorModel(), {"role": "user", "content": "9848012345"}, result)
    assert reply.tool_uses == []
    assert "advisor" in reply.text.lower()


# --- settings -------------------------------------------------------------------------------


def test_the_feature_is_off_by_default() -> None:
    s = settings()
    assert s.public_chat_tenant_slug is None and s.public_chat_server_key is None


def test_the_fake_provider_can_never_run_in_production() -> None:
    with pytest.raises(ValidationError, match="fake"):
        settings(
            environment="production",
            oidc_issuer="https://auth.example.test/realms/crm",
            files_s3_secure=True,
            public_chat_provider="fake",
        )


def test_the_server_key_must_be_long() -> None:
    with pytest.raises(ValidationError, match="32"):
        settings(public_chat_server_key=SecretStr("short"))


def test_the_model_follows_the_provider_setting() -> None:
    assert isinstance(
        build_public_chat_model(settings(public_chat_provider="fake")), FakeVisitorModel
    )
    # DeepSeek without a key: "not available", never a crash.
    assert build_public_chat_model(settings(public_chat_provider="deepseek")).available is False
