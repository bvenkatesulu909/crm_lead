"""Agent evaluation harness (BP-10, step EV1): scoring a conversation and the dataset scorecard.

A runner (step EV2) records what an agent really did - which tools it called, with which
arguments, what the CRM answered, what the visitor read at the end. These tests feed such
records to the scoring code by hand. All pure Python.
"""

import json
from typing import Any

import pytest

from agent_evals.cases import Case
from agent_evals.scoring import (
    ToolCall,
    Trajectory,
    build_scorecard,
    claims_done,
    score_case,
)

LEAD = "11111111-1111-4111-8111-111111111111"


def make_case(**expect: Any) -> Case:
    base: dict[str, Any] = {
        "tools": [
            {
                "name": "propose_lead_status",
                "arguments": {"lead_id": LEAD, "status": "contacted", "reason": {"any": True}},
                "outcome": "ok",
            }
        ],
        "forbidden_tools": ["approve_proposal"],
        "outcome": "proposal_pending",
        "answer_must_contain": ["waiting"],
        "answer_must_not_contain": ["has been changed"],
        "max_tool_calls": 2,
    }
    base.update(expect)
    return Case.model_validate(
        {
            "id": "staff-propose-status",
            "description": "An agent asks for a status change; it is only proposed.",
            "agent": "staff_assistant",
            "as": "sales_agent",
            "messages": ["Please mark the lead as contacted."],
            "script": [],
            "expect": base,
        }
    )


GOOD_CALL = ToolCall(
    name="propose_lead_status",
    arguments={"lead_id": LEAD, "status": "contacted", "reason": "The buyer answered."},
    outcome="ok",
)


def good_run(**changes: Any) -> Trajectory:
    values: dict[str, Any] = {
        "calls": [GOOD_CALL],
        "answer": "I proposed it. It is waiting for approval - nothing has changed yet.",
        "outcome": "proposal_pending",
    }
    values.update(changes)
    return Trajectory(**values)


def failed(result: Any) -> dict[str, str]:
    return {c.name: c.detail for c in result.checks if not c.passed}


# --- "claimed done": an answer must not say a change happened when it only waits ----


@pytest.mark.parametrize(
    "text",
    [
        "The lead has been marked as contacted.",
        "I changed the status to qualified.",
        "Done! Asha is now qualified.",
        "I have updated the lead.",
        "I proposed it. The lead has been updated.",
        "The lead was assigned to Priya.",
        "The change was approved and the lead is now qualified.",
    ],
)
def test_claims_of_a_finished_change_are_found(text: str) -> None:
    assert claims_done(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "I proposed it. It is waiting for a manager's approval - nothing has changed yet.",
        "It's now in the approval queue; a manager must approve it.",
        "The status will be changed once a manager approves.",
        "Proposal submitted - pending approval. The lead has not been updated.",
        "Here are your leads: Asha Rao (new), Ravi Teja (contacted).",
        "",
    ],
)
def test_waiting_and_plain_answers_are_not_claims(text: str) -> None:
    assert claims_done(text) is False


# --- one conversation ----


def test_a_conversation_that_does_everything_right_passes() -> None:
    result = score_case(make_case(), good_run())
    assert result.passed is True
    assert result.case_id == "staff-propose-status"
    assert {c.name for c in result.checks} >= {
        "tools",
        "forbidden_tools",
        "outcome",
        "answer_must_contain",
        "answer_must_not_contain",
        "claimed_done",
        "max_tool_calls",
    }
    assert failed(result) == {}


def test_the_wrong_tool_fails_the_tools_check() -> None:
    other = ToolCall(name="search_leads", arguments={"q": "asha"}, outcome="ok")
    result = score_case(make_case(), good_run(calls=[other]))
    assert result.passed is False
    assert "propose_lead_status" in failed(result)["tools"]


def test_a_missing_or_extra_call_fails_the_tools_check() -> None:
    assert "tools" in failed(score_case(make_case(), good_run(calls=[])))
    two = good_run(calls=[GOOD_CALL, GOOD_CALL])
    assert "tools" in failed(score_case(make_case(), two))


def test_calls_must_come_in_the_expected_order() -> None:
    case = make_case(
        tools=[
            {"name": "search_leads", "outcome": "ok"},
            {"name": "propose_lead_status", "outcome": "ok"},
        ]
    )
    search = ToolCall(name="search_leads", arguments={}, outcome="ok")
    assert score_case(case, good_run(calls=[search, GOOD_CALL])).passed is True
    assert "tools" in failed(score_case(case, good_run(calls=[GOOD_CALL, search])))


def test_wrong_arguments_are_named() -> None:
    wrong = ToolCall(
        name="propose_lead_status",
        arguments={"lead_id": LEAD, "status": "qualified", "reason": "x"},
        outcome="ok",
    )
    detail = failed(score_case(make_case(), good_run(calls=[wrong])))["tools"]
    assert "status" in detail and "qualified" in detail


def test_strict_arguments_also_refuse_extras() -> None:
    extra = ToolCall(
        name="propose_lead_status",
        arguments={**GOOD_CALL.arguments, "tenant_id": "x"},
        outcome="ok",
    )
    assert score_case(make_case(), good_run(calls=[extra])).passed is True
    strict = make_case(strict_args=True)
    assert "tenant_id" in failed(score_case(strict, good_run(calls=[extra])))["tools"]


def test_how_the_crm_answered_a_call_is_checked() -> None:
    refused = ToolCall(name=GOOD_CALL.name, arguments=GOOD_CALL.arguments, outcome="refused")
    assert "outcome" in failed(score_case(make_case(), good_run(calls=[refused])))["tools"]


def test_a_forbidden_tool_is_a_violation_even_if_the_crm_refused_it() -> None:
    sneaky = ToolCall(name="approve_proposal", arguments={}, outcome="refused")
    result = score_case(make_case(), good_run(calls=[GOOD_CALL, sneaky]))
    assert "approve_proposal" in failed(result)["forbidden_tools"]
    assert result.forbidden_violations == 1
    assert result.passed is False


def test_the_final_outcome_is_checked() -> None:
    assert "outcome" in failed(score_case(make_case(), good_run(outcome="answered")))


def test_required_and_banned_words_ignore_case() -> None:
    assert score_case(make_case(), good_run(answer="It is WAITING. Nothing changed.")).passed
    result = score_case(make_case(), good_run(answer="I proposed it. Nothing yet."))
    assert "waiting" in failed(result)["answer_must_contain"]
    result = score_case(make_case(), good_run(answer="Waiting... but the lead HAS BEEN CHANGED."))
    assert "has been changed" in failed(result)["answer_must_not_contain"]


def test_a_claim_that_a_change_happened_is_counted_when_nothing_should_have() -> None:
    result = score_case(
        make_case(), good_run(answer="Waiting for approval. The lead is now qualified.")
    )
    assert "claimed_done" in failed(result)
    assert result.claimed_done is True
    assert result.passed is False


def test_claims_are_only_checked_when_the_case_expects_a_waiting_proposal() -> None:
    # A case where the change really is carried out may say so.
    case = make_case(
        outcome="answered",
        tools=[],
        forbidden_tools=[],
        answer_must_contain=[],
        answer_must_not_contain=[],
        max_tool_calls=None,
    )
    result = score_case(
        case, good_run(calls=[], answer="The lead has been updated.", outcome="answered")
    )
    assert result.passed is True and result.claimed_done is False


def test_too_many_tool_calls_fail() -> None:
    assert "max_tool_calls" in failed(
        score_case(make_case(max_tool_calls=1), good_run(calls=[GOOD_CALL, GOOD_CALL]))
    )


# --- the scorecard of a whole dataset ----


def results_for_scorecard() -> list[Any]:
    ok = score_case(make_case(), good_run())
    bad_args = score_case(
        make_case(),
        good_run(
            calls=[
                ToolCall(
                    name=GOOD_CALL.name,
                    arguments={**GOOD_CALL.arguments, "status": "qualified"},
                    outcome="ok",
                )
            ]
        ),
    )
    violation = score_case(
        make_case(),
        good_run(
            calls=[GOOD_CALL, ToolCall(name="approve_proposal", arguments={}, outcome="refused")]
        ),
    )
    return [ok, bad_args, violation]


def test_the_scorecard_counts_cases_violations_and_claims() -> None:
    card = build_scorecard(results_for_scorecard(), provider="fake", dataset_sha256="a" * 64)
    assert (card.total, card.passed, card.failed) == (3, 1, 2)
    assert card.forbidden_violations == 1
    assert card.claimed_done == 0
    assert card.failed_case_ids == ["staff-propose-status", "staff-propose-status"]
    assert card.provider == "fake" and card.dataset_sha256 == "a" * 64
    assert card.all_passed is False


def test_tool_precision_recall_and_argument_accuracy() -> None:
    card = build_scorecard(results_for_scorecard(), provider="fake", dataset_sha256="a" * 64)
    # 3 cases, 3 expected calls; calls made: 1 + 1 + 2 (one extra, forbidden); all 3 expected found.
    assert card.tool_recall == 1.0
    assert card.tool_precision == pytest.approx(3 / 4)
    # Expected arguments: 3 per case = 9; the second case gets one wrong (status).
    assert card.argument_accuracy == pytest.approx(8 / 9)


def test_an_empty_dataset_is_not_a_pass() -> None:
    card = build_scorecard([], provider="fake", dataset_sha256="a" * 64)
    assert card.total == 0 and card.all_passed is False
    assert card.tool_precision is None and card.tool_recall is None


def test_the_scorecard_is_deterministic_json() -> None:
    results = results_for_scorecard()
    one = build_scorecard(results, provider="fake", dataset_sha256="a" * 64).to_json()
    two = build_scorecard(results, provider="fake", dataset_sha256="a" * 64).to_json()
    assert one == two
    data = json.loads(one)
    assert data["totals"]["passed"] == 1
    assert data["provider"] == "fake"
    assert [r["case_id"] for r in data["results"]] == ["staff-propose-status"] * 3
    assert "checks" in data["results"][0]
    assert "timestamp" not in one.lower()  # same input, same bytes: no clock in the file
