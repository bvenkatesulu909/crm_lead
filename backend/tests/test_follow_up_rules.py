"""The pure rules of automatic follow-ups (ADR 0036, FM3): who is due, when a draft may be made."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.communications import follow_up_rules as rules
from app.modules.communications.follow_up_rules import Facts, Policy

NOW = datetime(2026, 11, 21, 10, 30, tzinfo=UTC)
GOOD = Policy(enabled=True, template_id=uuid.uuid4())
# A lead who started the conversation themselves, with nothing in the way.
READY = Facts(now=NOW, started_by_person=True)


def reasons(policy: Policy = GOOD, facts: Facts = READY, rule: str = "task_due_today"):
    return rules.evaluate(policy, facts, rule).reasons


# --- the menu and the task rule ---------------------------------------------------------------


def test_the_menu_has_exactly_the_one_rule_the_owner_chose() -> None:
    assert list(rules.RULES) == ["task_due_today"]


@pytest.mark.parametrize(
    ("due", "done", "expected"),
    [
        (NOW, False, True),
        (NOW.replace(hour=0, minute=0), False, True),  # earlier today still counts
        (NOW.replace(hour=23, minute=59), False, True),
        (NOW - timedelta(days=1), False, False),  # overdue: due on another day
        (NOW + timedelta(days=1), False, False),
        (NOW, True, False),  # already done
    ],
)
def test_a_task_is_due_today_only_when_it_falls_today_and_is_not_done(due, done, expected) -> None:
    assert rules.is_task_due_today(due, done, NOW) is expected


# --- the happy path and the defaults -----------------------------------------------------------


def test_a_ready_candidate_is_allowed() -> None:
    decision = rules.evaluate(GOOD, READY)
    assert (decision.allowed, decision.reasons) == (True, [])


def test_the_default_policy_is_off_and_has_the_agreed_numbers() -> None:
    policy = Policy()
    assert (policy.enabled, policy.template_id) == (False, None)
    assert (policy.monthly_cap, policy.cooldown_days, policy.expiry_days) == (3, 7, 7)
    assert (policy.daily_cap, policy.pending_cap) == (100, 20)
    assert policy.problems() == []
    assert reasons(Policy(), READY) == ["switched_off", "no_template"]


# --- every stop condition, one at a time -------------------------------------------------------

CASES = [
    ("platform_off", GOOD, replace(READY, platform_enabled=False)),
    ("switched_off", replace(GOOD, enabled=False), READY),
    ("no_template", replace(GOOD, template_id=None), READY),
    ("consent_withdrawn", GOOD, replace(READY, consent="withdrawn")),
    ("consent_unknown", GOOD, replace(READY, started_by_person=False)),
    ("no_address", GOOD, replace(READY, has_address=False)),
    ("no_owner", GOOD, replace(READY, has_owner=False)),
    ("lead_closed", GOOD, replace(READY, lead_status="converted")),
    ("lead_closed", GOOD, replace(READY, lead_status="unqualified")),
    ("reply_received", GOOD, replace(READY, reply_after_trigger=True)),
    ("draft_waiting", GOOD, replace(READY, draft_waiting=True)),
    ("cooldown", GOOD, replace(READY, last_draft_at=NOW - timedelta(days=6, hours=23))),
    ("monthly_cap", GOOD, replace(READY, drafts_last_30_days=3)),
    ("daily_cap", GOOD, replace(READY, drafts_today=100)),
    ("owner_pending_cap", GOOD, replace(READY, waiting_for_owner=20)),
]


@pytest.mark.parametrize(("code", "policy", "facts"), CASES)
def test_each_stop_condition_alone_stops_a_draft(code, policy, facts) -> None:
    decision = rules.evaluate(policy, facts)
    assert decision.allowed is False
    assert decision.reasons == [code]


def test_an_unknown_rule_is_refused() -> None:
    assert reasons(rule="send_everyone_a_message") == ["unknown_rule"]


def test_every_reason_the_rules_can_give_is_listed_and_each_case_covers_one() -> None:
    covered = {code for code, _, _ in CASES} | {"unknown_rule", "bad_policy"}
    assert covered == set(rules.REASONS)


def test_all_the_reasons_are_reported_together_in_a_fixed_order() -> None:
    facts = replace(READY, consent="withdrawn", has_address=False, reply_after_trigger=True)
    assert reasons(GOOD, facts) == ["consent_withdrawn", "no_address", "reply_received"]


# --- the edges of each limit --------------------------------------------------------------------


def test_the_cooldown_ends_exactly_after_its_days() -> None:
    just_before = replace(READY, last_draft_at=NOW - timedelta(days=7) + timedelta(seconds=1))
    exactly = replace(READY, last_draft_at=NOW - timedelta(days=7))
    assert reasons(GOOD, just_before) == ["cooldown"]
    assert reasons(GOOD, exactly) == []
    assert reasons(GOOD, replace(READY, last_draft_at=None)) == []


def test_the_cooldown_follows_the_policy() -> None:
    facts = replace(READY, last_draft_at=NOW - timedelta(days=2))
    assert reasons(replace(GOOD, cooldown_days=3), facts) == ["cooldown"]
    assert reasons(replace(GOOD, cooldown_days=2), facts) == []


@pytest.mark.parametrize(
    ("fact", "policy_field", "reason"),
    [
        ("drafts_last_30_days", "monthly_cap", "monthly_cap"),
        ("drafts_today", "daily_cap", "daily_cap"),
        ("waiting_for_owner", "pending_cap", "owner_pending_cap"),
    ],
)
def test_a_cap_stops_at_the_cap_and_not_before(fact, policy_field, reason) -> None:
    cap: int = getattr(GOOD, policy_field)
    below: dict[str, Any] = {fact: cap - 1}
    at_cap: dict[str, Any] = {fact: cap}
    one: dict[str, Any] = {fact: 1}
    lower: dict[str, Any] = {policy_field: 1}
    assert reasons(GOOD, replace(READY, **below)) == []
    assert reasons(GOOD, replace(READY, **at_cap)) == [reason]
    # The policy's number is the one used: a lower cap stops sooner.
    assert reasons(replace(GOOD, **lower), replace(READY, **one)) == [reason]


# --- consent ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("consent", "started", "expected"),
    [
        ("granted", False, []),  # said yes: fine even if we started it
        ("granted", True, []),
        ("unknown", True, []),  # a service follow-up about a conversation they started
        ("unknown", False, ["consent_unknown"]),  # we would be writing out of the blue
        ("withdrawn", True, ["consent_withdrawn"]),  # a no always stops, whoever started it
        ("withdrawn", False, ["consent_withdrawn"]),
    ],
)
def test_consent_rules(consent, started, expected) -> None:
    assert reasons(GOOD, replace(READY, consent=consent, started_by_person=started)) == expected


def test_a_made_up_consent_value_does_not_count_as_a_yes() -> None:
    facts = replace(READY, consent="yes", started_by_person=False)
    assert reasons(GOOD, facts) == ["consent_unknown"]


# --- the policy's bounds ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"monthly_cap": 0},
        {"monthly_cap": 9},  # never above 8, whatever an administrator types
        {"daily_cap": 101},  # the owner's 100 a day is a ceiling
        {"daily_cap": 0},
        {"pending_cap": 21},
        {"expiry_days": 0},
        {"expiry_days": 31},
        {"cooldown_days": 0},
        {"cooldown_days": 61},
        {"monthly_cap": True},
        {"monthly_cap": "3"},
    ],
)
def test_numbers_outside_their_bounds_are_a_bad_policy(bad) -> None:
    policy = replace(GOOD, **bad)
    assert policy.problems() == [next(iter(bad))]
    assert reasons(policy) == ["bad_policy"]


@pytest.mark.parametrize(("name", "low_high"), list(rules.BOUNDS.items()))
def test_the_edges_of_every_bound_are_accepted(name, low_high) -> None:
    low, high = low_high
    edge_low: dict[str, Any] = {name: low}
    edge_high: dict[str, Any] = {name: high}
    assert replace(GOOD, **edge_low).problems() == []
    assert replace(GOOD, **edge_high).problems() == []


def test_the_agreed_ceilings() -> None:
    assert rules.BOUNDS["monthly_cap"][1] == 8
    assert rules.BOUNDS["daily_cap"][1] == 100
