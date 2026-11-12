"""Evaluation cases in Hindi and Telugu (ADR 0027, step VL3): the case format and the dataset.
The cases themselves are played against the database with the other website chat cases
(tests/db/test_agent_evals_public_chat.py)."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.cases import Case, dataset_hash, load_cases

CASES_DIR = Path(__file__).resolve().parents[1] / "evals" / "agents"
ALL = {case.id: case for case in load_cases(CASES_DIR)}
LANGUAGE_CASES = [c for c in ALL.values() if c.agent == "public_chat" and c.language != "en"]


def make(agent: str = "public_chat", **fields: Any) -> Case:
    persona = {"public_chat": "visitor", "staff_assistant": "sales_agent"}[agent]
    expect = fields.pop("expect", {"outcome": "answered"})
    return Case.model_validate(
        {
            "id": "public-language-format",
            "description": "A format check.",
            "agent": agent,
            "as": persona,
            "messages": ["Hello"],
            "expect": expect,
            **fields,
        }
    )


def test_a_case_plays_in_english_unless_it_says_otherwise() -> None:
    case = make()
    assert case.language == "en"
    assert case.expect.lead_language is None


@pytest.mark.parametrize("code", ["hi", "te", "en"])
def test_the_three_languages_are_accepted(code: str) -> None:
    assert (
        make(language=code, expect={"outcome": "answered", "lead_language": code}).language == code
    )


@pytest.mark.parametrize("bad", ["fr", "HI", "", "hindi"])
def test_any_other_language_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        make(language=bad)
    with pytest.raises(ValidationError):
        make(expect={"outcome": "answered", "lead_language": bad})


def test_only_the_website_chat_has_a_visitor_language() -> None:
    with pytest.raises(ValidationError, match="language"):
        make(agent="staff_assistant", language="hi")
    with pytest.raises(ValidationError, match="language"):
        make(agent="staff_assistant", expect={"outcome": "answered", "lead_language": "hi"})


def test_there_are_hindi_and_telugu_cases_for_the_important_protections() -> None:
    by_language = {
        code: {c.id for c in LANGUAGE_CASES if c.language == code} for code in ("hi", "te")
    }
    for code, ids in by_language.items():
        assert len(ids) >= 5, code
        names = " ".join(ids)
        for needed in ("save-lead", "card-number", "injection", "system-prompt", "link-removed"):
            assert needed in names, (code, needed)


def test_every_lead_saving_case_names_the_language_it_expects() -> None:
    for case in LANGUAGE_CASES:
        if case.expect.outcome == "lead_saved":
            assert case.expect.lead_language == case.language, case.id


def test_the_language_is_part_of_what_the_dataset_hash_covers() -> None:
    # dataset_hash() hashes every case's JSON dump, so a baseline says which languages it measured.
    dump = {"hi": make(language="hi"), "en": make()}
    assert dump["hi"].model_dump(mode="json", by_alias=True)["language"] == "hi"
    assert dump["en"].model_dump(mode="json", by_alias=True)["language"] == "en"
    assert dataset_hash(CASES_DIR) == dataset_hash(CASES_DIR)
