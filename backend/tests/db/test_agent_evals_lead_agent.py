# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (BP-10, step LA5): the lead agent, played for real.

Every case in evals/agents/lead_agent.json runs through the REAL ``run_lead_agent`` - the real
permission and record-level checks, limits, agent registry, the LangGraph graph with its read-only
looks, the strict check of the model's answer, Sentinel and approval queue, and the real test
database - with only the language model replaced by the case's script. Each case also gets checks
it cannot skip: nothing changed directly, proposals stored as pending, every finished run audited
once, never "converted".
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.lead_agent import rules
from tests.db.agent_eval_support import explain, play_lead_agent
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
LEAD_AGENT = [case for case in load_cases(CASES_DIR) if case.agent == "lead_agent"]
BY_ID = {case.id: case for case in LEAD_AGENT}
MATCHING = "lead-agent-qualifies-a-matching-lead"


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


def test_there_are_lead_agent_cases_for_every_suggestion() -> None:
    assert len(LEAD_AGENT) >= 15
    statuses = {
        call.arguments.get("status")
        for case in LEAD_AGENT
        for step in case.script
        for call in step.calls
    }
    assert {*rules.SUGGESTABLE, rules.NOTHING} <= statuses


@pytest.mark.parametrize("case", LEAD_AGENT, ids=lambda case: case.id)
def test_a_lead_agent_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_lead_agent(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_lead_agent_dataset_scores_clean(db_session: Session, world: World) -> None:
    # All cases in ONE transaction: a case must leave nothing behind for the next.
    results: list[CaseResult] = [play_lead_agent(db_session, world, case)[0] for case in LEAD_AGENT]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(LEAD_AGENT)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expectation_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(MATCHING, **{"expect.proposals.0.payload.status": "contacted"})
    result, _ = play_lead_agent(db_session, world, case)
    assert result.passed is False


def test_a_missing_proposal_is_caught(db_session: Session, world: World) -> None:
    case = variant(MATCHING, **{"expect.proposals": []})
    result, _ = play_lead_agent(db_session, world, case)
    assert result.passed is False


def test_a_forbidden_tool_is_caught(db_session: Session, world: World) -> None:
    case = variant(MATCHING, **{"expect.forbidden_tools": ["submit_suggestion"]})
    result, _ = play_lead_agent(db_session, world, case)
    assert result.passed is False


def test_a_proposal_that_converts_a_lead_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the plan ever asked for a conversion, the extra check must fail the case.
    real = rules.plan

    def converting(*args: Any, **kwargs: Any) -> Any:
        planned = real(*args, **kwargs)
        if planned is not None:
            return type(planned)(
                planned.kind, planned.target_type, {"status": "converted"}, planned.reason
            )
        return planned

    monkeypatch.setattr(rules, "plan", converting)
    result, _ = play_lead_agent(db_session, world, BY_ID[MATCHING])
    assert result.passed is False


def test_a_case_without_governance_plays_the_agent_switched_on(
    db_session: Session, world: World
) -> None:
    """The agent starts OFF in the registry; the harness switches it on for an ordinary case and
    leaves a switched-off case as it is (so 'off' cases really test the switch)."""
    on, _ = play_lead_agent(db_session, world, BY_ID[MATCHING])
    off, _ = play_lead_agent(db_session, world, BY_ID["lead-agent-switched-off-does-nothing"])
    assert on.passed and off.passed
