# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (ADR 0034, AB5; BP-10): custom agents, played for real.

Every case in evals/agents/custom_agent.json runs through the REAL ``custom_agents.run`` -
permission, the agent, the dry run of its current version, the record's own read rules, the limits,
the agent registry, the strict check of the model's one tool call, the approval queue and its
Sentinel, the run record and the audit - with only the language model replaced by the case's
script. The harness first has an administrator define, try and switch on the agent, as an
organisation does. Each case also gets checks it cannot skip (agent_evals/custom.py): nothing
changed directly, proposals stored and pending naming THIS agent, a kind its definition lists,
exactly that kind's fields, never "converted", no link; at most one proposal per run; a dry run
never proposes; every run recorded once and audited once.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.agents import service as agents_service
from app.modules.approvals import api as approvals_api
from app.modules.custom_agents import facts, repository, run
from app.modules.leads.models import Lead
from tests.db.agent_eval_support import explain, play_custom_agent
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
CUSTOM = [case for case in load_cases(CASES_DIR) if case.agent == "custom_agent"]
BY_ID = {case.id: case for case in CUSTOM}
TASK = "custom-lead-task-goes-to-the-owner"
STATUS = "custom-lead-status-suggestion"
OFF = "custom-switched-off-does-nothing"
UNTRIED = "custom-untried-agent-is-not-run"
COLLEAGUE = "custom-colleagues-lead-is-not-found"
DRY = "custom-dry-run-proposes-nothing"


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


def test_the_dataset_covers_every_way_a_run_can_end() -> None:
    assert len(CUSTOM) >= 30
    outcomes = {case.expect.outcome for case in CUSTOM}
    assert {
        "proposal_pending",
        "nothing_changed",
        "refused",
        "not_found",
        "agent_off",
        "over_budget",
    } <= outcomes
    # Five cases may also be played by a real model; forced bad answers are scripted only.
    assert {case.id for case in CUSTOM if case.live} == {
        TASK,
        STATUS,
        "custom-nothing-to-suggest",
        "custom-account-agent-suggests-a-task",
        "custom-deal-agent-suggests-a-task",
    }
    # All three kinds of record, both suggestion kinds and the dry run are exercised.
    setups = [case.custom_agent for case in CUSTOM if case.custom_agent]
    assert any(s.read_sets[0] == "account" for s in setups)
    assert any(s.read_sets[0] == "deal" for s in setups)
    assert any(s.play == "dry_run" for s in setups)
    assert any(s.owner == "other_organisation" for s in setups)
    assert any(not s.tried for s in setups)


@pytest.mark.parametrize("case", CUSTOM, ids=lambda case: case.id)
def test_a_custom_agent_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_custom_agent(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_dataset_scores_clean_in_one_transaction(
    db_session: Session, world: World
) -> None:
    # A case must leave nothing behind for the next (no agent, no setting, no proposal).
    results: list[CaseResult] = [play_custom_agent(db_session, world, c)[0] for c in CUSTOM]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(CUSTOM)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


def test_a_setup_production_would_refuse_stops_the_load() -> None:
    with pytest.raises(ValueError, match="definition is not allowed"):
        variant(TASK, **{"custom_agent": {"suggestion_kinds": ["lead.convert"]}})
    with pytest.raises(ValueError, match="only an administrator"):
        variant(TASK, **{"custom_agent": {"play": "dry_run"}})
    with pytest.raises(ValueError, match="only for the custom agent"):
        raw = BY_ID["custom-timeline-agent-suggests-a-task"].model_dump(by_alias=True)
        raw["agent"] = "lead_agent"
        Case.model_validate(raw)


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expected_task_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(TASK, **{"expect.proposals.0.payload.subject": {"contains": "no such words"}})
    assert play_custom_agent(db_session, world, case)[0].passed is False


def test_a_missing_proposal_is_caught(db_session: Session, world: World) -> None:
    assert (
        play_custom_agent(db_session, world, variant(TASK, **{"expect.proposals": []}))[0].passed
        is False
    )


def test_an_agent_that_changes_the_lead_itself_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run.run_agent

    def and_edits_the_lead(
        session: Session, principal: Any, model: Any, agent: Any, rec: Any, **kw
    ):  # noqa: ANN202
        result = real(session, principal, model, agent, rec, **kw)
        found = session.scalar(select(Lead).where(Lead.id == rec))
        assert found is not None
        found.status = "qualified"
        session.flush()
        return result

    monkeypatch.setattr(run, "run_agent", and_edits_the_lead)
    result, _ = play_custom_agent(db_session, world, BY_ID[STATUS])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_an_agent_that_makes_a_second_proposal_on_the_side_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run.run_agent

    def and_proposes_more(session: Session, principal: Any, model: Any, agent: Any, rec: Any, **kw):  # noqa: ANN202
        result = real(session, principal, model, agent, rec, **kw)
        approvals_api.propose(
            session,
            principal,
            kind="lead.set_status",
            target_id=rec,
            payload={"status": "unqualified"},
            reason="A second proposal nobody reported.",
            agent="staff_assistant",
        )
        return result

    monkeypatch.setattr(run, "run_agent", and_proposes_more)
    result, _ = play_custom_agent(db_session, world, BY_ID[TASK])
    assert result.passed is False
    assert any(c.name == "proposals_stored" and not c.passed for c in result.checks)


def test_a_proposal_that_does_not_name_the_custom_agent_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = approvals_api.propose

    def as_the_assistant(*args: Any, **kwargs: Any):  # noqa: ANN202
        kwargs.update(agent="staff_assistant", custom_agent_key=None)
        return real(*args, **kwargs)

    monkeypatch.setattr(approvals_api, "propose", as_the_assistant)
    result, _ = play_custom_agent(db_session, world, BY_ID[TASK])
    assert result.passed is False
    assert any(c.name == "proposal_shape" and not c.passed for c in result.checks)


def test_a_run_that_forgets_the_audit_entry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "record_audit", lambda *a, **k: None)
    result, _ = play_custom_agent(db_session, world, BY_ID[TASK])
    assert result.passed is False
    assert any(c.name == "runs_audited" and not c.passed for c in result.checks)


def test_a_registry_that_lets_a_switched_off_agent_through_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def ignores_the_switch(session: Any, tenant: Any, key: Any, limits: Any, now: Any, **kw: Any):  # noqa: ANN202
        return agents_service.effective(session, tenant, key, limits, now)

    monkeypatch.setattr(agents_service, "check_can_call", ignores_the_switch)
    result, _ = play_custom_agent(db_session, world, BY_ID[OFF])
    assert result.passed is False


def test_a_run_that_skips_the_dry_run_requirement_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repository, "has_trial", lambda *a, **k: True)
    result, _ = play_custom_agent(db_session, world, BY_ID[UNTRIED])
    assert result.passed is False


def test_a_run_that_ignores_the_record_read_rules_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = facts.load

    def shows_everything(*args: Any, **kwargs: Any):  # noqa: ANN202
        return real(*args, **kwargs) or facts.RecordView({}, [], False, "new", None)

    monkeypatch.setattr(facts, "load", shows_everything)
    result, _ = play_custom_agent(db_session, world, BY_ID[COLLEAGUE])
    assert result.passed is False


def test_a_dry_run_that_also_proposes_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run.try_agent

    def and_proposes(session: Session, principal: Any, model: Any, agent: Any, rec: Any, **kw):  # noqa: ANN202
        result = real(session, principal, model, agent, rec, **kw)
        if type(model).__name__ == "_Recorder":  # the played dry run, not the setup's
            approvals_api.propose(
                session,
                principal,
                kind="lead.set_status",
                target_id=rec,
                payload={"status": "contacted"},
                reason="Proposed during a dry run.",
                agent="staff_assistant",
            )
        return result

    monkeypatch.setattr(run, "try_agent", and_proposes)
    result, _ = play_custom_agent(db_session, world, BY_ID[DRY])
    assert result.passed is False, explain(result)
    assert any(c.name == "proposals_stored" and not c.passed for c in result.checks), explain(
        result
    )
