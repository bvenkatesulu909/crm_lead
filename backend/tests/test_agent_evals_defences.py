"""Evaluation cases about the injection defences (ADR 0018, step VA4): the case format and the
dataset. The cases are played against the database with the other cases of their agent
(tests/db/test_agent_evals_*.py); ``expect.stored_must_*`` checks what the website chat stored."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_evals.cases import Case, load_cases

CASES_DIR = Path(__file__).resolve().parents[1] / "evals" / "agents"
ALL = {case.id: case for case in load_cases(CASES_DIR)}
DEFENCE_CASES = [case for case in ALL.values() if "-defence-" in case.id]


def make(**expect: object) -> Case:
    return Case.model_validate(
        {
            "id": "public-defence-format",
            "description": "A format check.",
            "agent": "public_chat",
            "as": "visitor",
            "messages": ["Hello"],
            "expect": {"outcome": "answered", **expect},
        }
    )


def test_stored_text_checks_are_optional_and_empty_by_default() -> None:
    expect = make().expect
    assert expect.stored_must_contain == [] and expect.stored_must_not_contain == []


def test_stored_text_checks_are_read() -> None:
    expect = make(stored_must_contain=["cleaned"], stored_must_not_contain=["evil.example"]).expect
    assert expect.stored_must_contain == ["cleaned"]
    assert expect.stored_must_not_contain == ["evil.example"]


def test_stored_text_checks_belong_to_the_website_chat() -> None:
    """Only the website chat stores visitor text in the CRM; others would never be checked."""
    with pytest.raises(ValidationError, match="stored"):
        Case.model_validate(
            {
                "id": "staff-defence-format",
                "description": "x",
                "agent": "staff_assistant",
                "as": "sales_agent",
                "messages": ["Hello"],
                "expect": {"outcome": "answered", "stored_must_not_contain": ["x"]},
            }
        )


def test_there_are_defence_cases_for_every_entrance() -> None:
    assert {case.agent for case in DEFENCE_CASES} == {
        "staff_assistant",
        "portal_assistant",
        "public_chat",
    }
    assert len(DEFENCE_CASES) >= 6


def test_the_exit_cases_forbid_the_outside_address_in_the_answer() -> None:
    exits = [c for c in DEFENCE_CASES if "-exit-" in c.id and "internal" not in c.id]
    assert len(exits) >= 3
    for case in exits:
        assert case.expect.answer_must_not_contain, case.id
        assert any(
            "[link removed]" in w or "[image removed]" in w for w in case.expect.answer_must_contain
        ), case.id


def test_the_door_cases_check_what_was_stored() -> None:
    doors = [c for c in DEFENCE_CASES if "-door-" in c.id]
    assert any(c.expect.stored_must_not_contain for c in doors)
    assert any(c.expect.stored_must_contain for c in doors)


def test_cases_that_force_a_bad_model_output_are_not_played_by_a_real_model() -> None:
    assert all(case.live is False for case in DEFENCE_CASES)
