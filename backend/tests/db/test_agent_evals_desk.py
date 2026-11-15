# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (ADR 0024, step DD5): the deal desk and account research, played for
real.

Every case in evals/agents/deal_desk.json and account_research.json runs through the REAL
``run_review`` / ``run_research`` - permission, the record-level reads as the person asking, the
limits, the agent registry, the strict answer checks, the approval queue and its Sentinel, the
stored review or brief and the audit - with only the language model replaced by the case's
script. The deal desk's three reviewers really run at the same time, in threads. Each case also
gets checks it cannot skip (agent_evals/desk.py).
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.deal_desk import api as deal_desk_api
from app.modules.deal_desk import research_rules, review
from app.modules.sales.models import Opportunity
from tests.db.agent_eval_support import explain, play_account_research, play_deal_desk
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
EVERY = load_cases(CASES_DIR)
DESK = [case for case in EVERY if case.agent == "deal_desk"]
RESEARCH = [case for case in EVERY if case.agent == "account_research"]
BY_ID = {case.id: case for case in [*DESK, *RESEARCH]}
TWO_TASKS = "desk-two-tasks-wait-for-approval"
FOREIGN = "desk-reviewer-cites-another-sheet"
CITED = "research-cited-brief"
UNCITED = "research-uncited-sentence-removed"


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


def test_there_are_cases_for_both_agents() -> None:
    assert len(DESK) >= 15 and len(RESEARCH) >= 10
    outcomes = {case.expect.outcome for case in DESK}
    assert {"proposal_pending", "answered", "refused", "not_found", "agent_off"} <= outcomes
    # Every reviewer is the subject of a refused answer somewhere.
    refused = {
        role
        for case in DESK
        for role, verdict in (case.expect.reviewers or {}).items()
        if verdict == "refused"
    }
    assert refused == {"pricing", "account", "momentum"}


@pytest.mark.parametrize("case", DESK, ids=lambda case: case.id)
def test_a_deal_desk_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_deal_desk(db_session, world, case)
    assert result.passed, explain(result)


@pytest.mark.parametrize("case", RESEARCH, ids=lambda case: case.id)
def test_an_account_research_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_account_research(db_session, world, case)
    assert result.passed, explain(result)


def test_both_datasets_score_clean_in_one_transaction(db_session: Session, world: World) -> None:
    # A case must leave nothing behind for the next.
    results: list[CaseResult] = [play_deal_desk(db_session, world, c)[0] for c in DESK]
    results += [play_account_research(db_session, world, c)[0] for c in RESEARCH]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(DESK) + len(RESEARCH)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expected_task_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(TWO_TASKS, **{"expect.proposals.1.payload.subject": "Offer a discount"})
    result, _ = play_deal_desk(db_session, world, case)
    assert result.passed is False


def test_a_missing_task_is_caught(db_session: Session, world: World) -> None:
    case = variant(TWO_TASKS, **{"expect.proposals": []})
    result, _ = play_deal_desk(db_session, world, case)
    assert result.passed is False


def test_a_reviewer_that_may_cite_any_record_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the "only records of your own sheet" rule the pricing reviewer's answer counts.
    real = review.parse_findings

    def lenient(uses: list[Any], sheet: Any) -> list[review.Finding]:
        try:
            return real(uses, sheet)
        except review.AnswerRefusedError:
            return []

    monkeypatch.setattr(review, "parse_findings", lenient)
    result, _ = play_deal_desk(db_session, world, BY_ID[FOREIGN])
    assert result.passed is False


def test_a_desk_that_changes_the_deal_itself_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = deal_desk_api.run_review

    def and_moves_the_stage(session: Session, principal: Any, model: Any, deal: Any, **kw: Any):  # noqa: ANN202
        result = real(session, principal, model, deal, **kw)
        found = session.scalar(select(Opportunity).where(Opportunity.id == deal))
        assert found is not None
        found.stage = "negotiation"
        session.flush()
        return result

    monkeypatch.setattr(deal_desk_api, "run_review", and_moves_the_stage)
    result, _ = play_deal_desk(db_session, world, BY_ID[TWO_TASKS])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_a_brief_that_keeps_unsourced_sentences_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def keeps_everything(uses: list[Any], gathered: Any) -> research_rules.Brief:
        items = uses[0].input["sentences"]
        return research_rules.Brief(
            tuple(research_rules.Sentence(str(i["text"]), ()) for i in items), 0
        )

    monkeypatch.setattr(research_rules, "parse", keeps_everything)  # what research.py calls
    result, _ = play_account_research(db_session, world, BY_ID[UNCITED])
    assert result.passed is False
    assert any(c.name == "sentences_sourced" and not c.passed for c in result.checks)


def test_a_wrong_sentence_count_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(CITED, **{"expect.brief_sentences": 1})
    result, _ = play_account_research(db_session, world, case)
    assert result.passed is False


def test_a_case_without_governance_plays_research_switched_on(
    db_session: Session, world: World
) -> None:
    """Account research starts OFF in the registry; the harness switches it on for an ordinary
    case and leaves a switched-off case as it is (so the 'off' case really tests the switch)."""
    on, _ = play_account_research(db_session, world, BY_ID[CITED])
    off, _ = play_account_research(db_session, world, BY_ID["research-switched-off"])
    assert on.passed and off.passed
