# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (BP-10, step EV2): the staff assistant's cases, played for real.

Every case in evals/agents/staff_assistant.json runs through the REAL staff assistant - real
tools, real permission checks, the real PostgreSQL test database - with only the language model
replaced by the case's script. A failing case fails the pull request (docs/agent-evals.md).
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.assistant import staff_tools
from tests.db.agent_eval_support import explain, play_staff
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
STAFF = [case for case in load_cases(CASES_DIR) if case.agent == "staff_assistant"]
BY_ID = {case.id: case for case in STAFF}


def variant(case_id: str, **changes: Any) -> Case:
    """A changed copy of a real case, to see the gate notice the change."""
    raw = BY_ID[case_id].model_dump(by_alias=True)
    for path, value in changes.items():
        target: Any = raw
        *parents, last = path.split(".")
        for part in parents:
            target = target[int(part)] if part.isdigit() else target[part]
        target[int(last) if last.isdigit() else last] = value
    return Case.model_validate(raw)


# --- every case of the dataset --------------------------------------------------------------------


def test_there_are_staff_cases() -> None:
    assert len(STAFF) >= 12


@pytest.mark.parametrize("case", STAFF, ids=lambda case: case.id)
def test_a_staff_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_staff(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_staff_dataset_scores_clean(db_session: Session, world: World) -> None:
    results: list[CaseResult] = [play_staff(db_session, world, case)[0] for case in STAFF]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(STAFF)
    assert card.all_passed, card.to_json()
    assert card.forbidden_violations == 0 and card.claimed_done == 0
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0
    assert card.argument_accuracy == 1.0


# --- the gate can fail: a change in what is expected, or in what the CRM does, is noticed ---------


def test_a_wrong_expectation_fails_the_case(db_session: Session, world: World) -> None:
    case = variant("staff-propose-contacted", **{"expect.tools.0.arguments.status": "qualified"})
    result, _ = play_staff(db_session, world, case)
    assert result.passed is False
    assert "status" in explain(result)


def test_a_forbidden_tool_call_is_caught_even_when_the_crm_refuses_it(
    db_session: Session, world: World
) -> None:
    case = variant("staff-no-approve-tool", **{"expect.forbidden_tools": ["approve_proposal"]})
    result, _ = play_staff(db_session, world, case)
    assert result.passed is False
    assert result.forbidden_violations == 1


def test_an_answer_that_claims_a_change_happened_is_caught(
    db_session: Session, world: World
) -> None:
    case = variant(
        "staff-propose-contacted",
        **{"script.1.say": "Done - the lead has been marked as contacted."},
    )
    result, _ = play_staff(db_session, world, case)
    assert result.passed is False
    assert result.claimed_done is True


def test_a_removed_proposal_limit_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If someone raised the per-answer limit, the "fourth proposal refused" case must fail.
    monkeypatch.setattr(staff_tools, "MAX_PROPOSALS_PER_ANSWER", 10)
    result, _ = play_staff(db_session, world, BY_ID["staff-fourth-proposal-refused"])
    assert result.passed is False
    assert "tools" in explain(result)


def test_a_case_that_is_never_played_to_the_end_is_an_error_not_a_pass(
    db_session: Session, world: World
) -> None:
    from agent_evals.runner import RunnerError

    # Four rounds of tool calls: the assistant stops after three, the last results are never
    # returned to the model, so the case can't say how the CRM answered. That must be loud.
    call = {"name": "search_leads", "arguments": {"q": ""}}
    case = variant("staff-read-leads", script=[{"calls": [call]}] * 4)
    with pytest.raises(RunnerError, match="never returned"):
        play_staff(db_session, world, case)
