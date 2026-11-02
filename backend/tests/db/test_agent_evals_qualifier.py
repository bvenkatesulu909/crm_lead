# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (BP-10, step QA5): the Qualifier, played for real.

Every case in evals/agents/qualifier.json runs through the REAL ``assess_lead`` - the real
permission and record-level checks, procedure lookup, limits, agent registry, strict check of the
model's answer, Sentinel and approval queue, and the real test database - with only the language
model replaced by the case's script. Each case also gets checks it cannot skip: nothing changed
directly, proposals stored as pending, one assessment stored per successful ask, never "converted".
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.qualifier import rules
from tests.db.agent_eval_support import explain, play_qualifier
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
QUALIFIER = [case for case in load_cases(CASES_DIR) if case.agent == "qualifier"]
BY_ID = {case.id: case for case in QUALIFIER}


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


def test_there_are_qualifier_cases() -> None:
    assert len(QUALIFIER) >= 20
    # Every decision the Qualifier can make is covered by a case.
    decisions = {
        call.arguments.get("decision")
        for case in QUALIFIER
        for step in case.script
        for call in step.calls
    }
    assert {"qualify", "unqualify", "contact_first", "need_info", "no_change"} <= decisions


@pytest.mark.parametrize("case", QUALIFIER, ids=lambda case: case.id)
def test_a_qualifier_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_qualifier(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_qualifier_dataset_scores_clean(db_session: Session, world: World) -> None:
    # All cases in ONE transaction: a case must leave nothing behind for the next.
    results: list[CaseResult] = [play_qualifier(db_session, world, case)[0] for case in QUALIFIER]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(QUALIFIER)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expectation_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(
        "qualifier-qualifies-a-matching-lead", **{"expect.proposals.0.payload.status": "contacted"}
    )
    result, _ = play_qualifier(db_session, world, case)
    assert result.passed is False


def test_a_missing_proposal_is_caught(db_session: Session, world: World) -> None:
    # The case says nothing is proposed; the script asks for a qualification, so a proposal exists.
    case = variant("qualifier-qualifies-a-matching-lead", **{"expect.proposals": []})
    result, _ = play_qualifier(db_session, world, case)
    assert result.passed is False


def test_a_forbidden_tool_is_caught(db_session: Session, world: World) -> None:
    case = variant(
        "qualifier-qualifies-a-matching-lead", **{"expect.forbidden_tools": ["submit_assessment"]}
    )
    result, _ = play_qualifier(db_session, world, case)
    assert result.passed is False


def test_a_proposal_that_converts_a_lead_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the mapping ever planned a conversion, the extra check must fail the case.
    real = rules.plan

    def converting(*args: Any, **kwargs: Any) -> Any:
        planned = real(*args, **kwargs)
        if planned is not None and planned.kind == "lead.set_status":
            payload = {"status": "converted"}
            return type(planned)(planned.kind, planned.target_type, payload, planned.reason)
        return planned

    monkeypatch.setattr(rules, "plan", converting)
    result, _ = play_qualifier(db_session, world, BY_ID["qualifier-qualifies-a-matching-lead"])
    assert result.passed is False


def test_a_changed_decision_mapping_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If "qualify" were mapped to the wrong status, the proposal check must notice.
    monkeypatch.setitem(rules.STATUS_FOR, "qualify", "contacted")
    result, _ = play_qualifier(db_session, world, BY_ID["qualifier-qualifies-a-matching-lead"])
    assert result.passed is False
