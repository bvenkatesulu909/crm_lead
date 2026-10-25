"""Agent evaluation harness (BP-10, step EV1): argument matchers.

A case says what a tool call's arguments must look like. A plain value must be equal; a
one-key object such as {"any_uuid": true} is a matcher. All pure Python - no database.
"""

import uuid
from typing import Any

import pytest

from agent_evals.matchers import MatcherError, check_arguments, compile_matcher

UUID = str(uuid.uuid4())


def check(spec: Any, value: Any = None, *, present: bool = True) -> str | None:
    return compile_matcher(spec).check(present=present, value=value)


# --- plain values must be equal ----------------------------------------------------------------


@pytest.mark.parametrize(
    "spec, value",
    [("contacted", "contacted"), (3, 3), (True, True), (None, None), (["a", "b"], ["a", "b"])],
)
def test_a_plain_value_must_be_equal(spec: Any, value: Any) -> None:
    assert check(spec, value) is None


@pytest.mark.parametrize(
    "spec, value",
    [("contacted", "qualified"), (3, 4), (3, "3"), (1, True), (True, 1), (None, "")],
)
def test_a_different_value_or_type_is_a_problem(spec: Any, value: Any) -> None:
    assert "expected" in (check(spec, value) or "")


def test_a_plain_value_needs_the_argument_to_be_there() -> None:
    assert "missing" in (check("x", present=False) or "")


# --- the matchers --------------------------------------------------------------------------------


def test_any_accepts_whatever_is_there_but_not_a_missing_argument() -> None:
    assert check({"any": True}, "whatever") is None
    assert check({"any": True}, None) is None
    assert "missing" in (check({"any": True}, present=False) or "")


def test_any_uuid() -> None:
    assert check({"any_uuid": True}, UUID) is None
    assert check({"any_uuid": True}, UUID.upper()) is None
    assert "UUID" in (check({"any_uuid": True}, "not-a-uuid") or "")
    assert "UUID" in (check({"any_uuid": True}, 12) or "")


def test_one_of() -> None:
    assert check({"one_of": ["contacted", "qualified"]}, "qualified") is None
    assert "one of" in (check({"one_of": ["contacted", "qualified"]}, "new") or "")


def test_matches_uses_the_whole_text() -> None:
    assert check({"matches": r"\d{3}"}, "123") is None
    assert "match" in (check({"matches": r"\d{3}"}, "1234") or "")
    assert "match" in (check({"matches": r"\d{3}"}, 123) or "")


def test_contains_ignores_case_and_needs_text() -> None:
    assert check({"contains": "call"}, "The buyer answered my CALL today.") is None
    assert "contain" in (check({"contains": "call"}, "email") or "")
    assert "contain" in (check({"contains": "call"}, 5) or "")


def test_absent_means_the_argument_must_not_be_sent() -> None:
    assert check({"absent": True}, present=False) is None
    assert "must not" in (check({"absent": True}, "x") or "")


# --- mistakes in a case are found when it is loaded -----------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        {"unknown_matcher": 1},
        {"any": True, "any_uuid": True},  # two keys
        {},  # nothing
        {"matches": "("},  # not a regular expression
        {"one_of": "contacted"},  # must be a list
        {"one_of": []},
        {"contains": 5},
        {"any": False},
        {"nested": {"any": True}},
    ],
)
def test_a_broken_matcher_is_refused(spec: Any) -> None:
    with pytest.raises(MatcherError):
        compile_matcher(spec)


# --- a whole argument dictionary -----------------------------------------------------------------


def test_every_expected_argument_is_checked_and_extra_ones_are_allowed() -> None:
    expected = {"lead_id": {"any_uuid": True}, "status": "contacted"}
    ok = {"lead_id": UUID, "status": "contacted", "reason": "free text"}
    assert check_arguments(expected, ok) == []


def test_problems_name_the_argument() -> None:
    expected = {"lead_id": {"any_uuid": True}, "status": "contacted", "reason": {"any": True}}
    problems = check_arguments(expected, {"lead_id": "x", "status": "qualified"})
    assert len(problems) == 3
    assert any(p.startswith("lead_id:") for p in problems)
    assert any(p.startswith("status:") and "expected" in p for p in problems)
    assert any(p.startswith("reason:") and "missing" in p for p in problems)


def test_strict_mode_also_refuses_arguments_nobody_expected() -> None:
    expected = {"status": "contacted"}
    actual = {"status": "contacted", "tenant_id": UUID}
    assert check_arguments(expected, actual) == []
    assert check_arguments(expected, actual, strict=True) == ["tenant_id: not expected"]
