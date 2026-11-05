# ruff: noqa: F811, F401 - fixtures are imported and used as parameters
"""The lead agent end to end (ADR 0022, step LA2): registry, limits, proposals, audit.

It is an agent of the registry that starts SWITCHED OFF; when on it reads one lead the asker may
see, asks the governed model once, and stores at most one PENDING proposal (through the approval
queue and the Sentinel). It never changes a lead.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.errors import ForbiddenError
from app.modules.agents import api as agents_api
from app.modules.agents.service import AgentBudgetReachedError, AgentUnavailableError
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ToolUse
from app.modules.lead_agent import api as lead_agent
from app.modules.leads.models import Lead
from app.modules.qualifier.api import NoActiveProcedureError
from tests.db.test_approvals import Acting, acting, add_lead, alpha
from tests.db.test_qualifier_assess import (
    EMAIL,
    PHONE,
    STEPS,
    ScriptedModel,
    lead_with_details,
    write_procedure,
)
from tests.db.test_quotes_api import World, world

KEY = "lead_agent"
AI = agents_api.Limits(platform_disabled=False, default_monthly_tokens=1000)
NOW = datetime.now(UTC)
LIMITS = lead_agent.Limits(per_lead_hour=5, per_tenant_day=100)


def says(status: str = "qualified", reason: str = "Budget and area are given.") -> ScriptedModel:
    return ScriptedModel(ToolUse("t1", "submit_suggestion", {"status": status, "reason": reason}))


def run(
    acting: Acting,
    who: str,
    model: Any,
    lead: Lead,
    *,
    limits: lead_agent.Limits = LIMITS,
    ai: agents_api.Limits = AI,
) -> lead_agent.RunResult:
    return lead_agent.run_lead_agent(
        acting.session, acting.who(who), model, lead.id, limits=limits, ai_limits=ai
    )


def configure(acting: Acting, **changes: Any) -> None:
    principal = acting.who("alpha.admin")
    current = agents_api.get_agent(acting.session, principal, KEY, AI, NOW)
    kwargs: dict[str, Any] = dict(changes)
    if current.version is not None:
        kwargs["version"] = current.version
    agents_api.update_settings(acting.session, principal, KEY, limits=AI, now=NOW, **kwargs)
    acting.session.flush()


def proposals(db: Session, world: World) -> list[AgentAction]:
    bind_tenant(db, alpha(world))
    return list(db.scalars(select(AgentAction).where(AgentAction.agent == KEY)).all())


def audits(db: Session, world: World) -> list[AuditLog]:
    bind_tenant(db, alpha(world))
    return list(db.scalars(select(AuditLog).where(AuditLog.action == lead_agent_audit())).all())


def lead_agent_audit() -> str:
    from app.modules.lead_agent.service import AUDIT_ACTION

    return AUDIT_ACTION


@pytest.fixture
def lead(acting: Acting, db_session: Session, world: World) -> Lead:
    return lead_with_details(db_session, world)


def switch_on(acting: Acting) -> None:
    """Switched on in the registry, and the organisation has written its qualification steps -
    the lead agent judges a lead by them (docs/lead-agent.md)."""
    configure(acting, enabled=True)
    write_procedure(acting)


@pytest.fixture
def on(acting: Acting, lead: Lead) -> Lead:
    switch_on(acting)
    return lead


# --- it is an agent of the registry, and it starts OFF ----------------------------------------


def test_it_is_listed_with_its_one_tool_and_starts_off(acting, lead) -> None:
    state = agents_api.get_agent(acting.session, acting.who("alpha.admin"), KEY, AI, NOW)
    assert state.enabled is False and state.agent.uses_model is True
    assert state.agent.tools == ("submit_suggestion",) and state.agent.default_enabled is False


def test_switched_off_it_never_reaches_the_model_and_stores_nothing(
    acting, db_session, world, lead
) -> None:
    model = says()
    with pytest.raises(AgentUnavailableError):
        run(acting, "alpha.agent1", model, lead)
    assert model.calls == []
    assert proposals(db_session, world) == [] and audits(db_session, world) == []


def test_the_platform_switch_and_the_budget_stop_it(acting, db_session, world, on) -> None:
    model = says()
    with pytest.raises(AgentUnavailableError):
        run(acting, "alpha.agent1", model, on, ai=agents_api.Limits(True, 1000))
    agents_api.record_usage(
        db_session, alpha(world), KEY, input_tokens=1000, output_tokens=0, limits=AI, now=NOW
    )
    with pytest.raises(AgentBudgetReachedError):
        run(acting, "alpha.agent1", model, on)
    assert model.calls == []


# --- what it does -----------------------------------------------------------------------------


def test_it_stores_one_pending_proposal_and_changes_nothing(acting, db_session, world, on) -> None:
    result = run(acting, "alpha.agent1", says("qualified"), on)
    assert result.outcome == "proposed" and result.proposal is not None
    (stored,) = proposals(db_session, world)
    assert (stored.status, stored.kind, stored.payload) == (
        "pending",
        "lead.set_status",
        {"status": "qualified"},
    )
    assert stored.reason.startswith("Lead agent: ") and stored.id == result.proposal.id
    db_session.refresh(on)
    assert on.status == "new"  # the lead itself did not change


def test_every_run_is_audited_with_codes_and_ids_only(acting, db_session, world, on) -> None:
    result = run(acting, "alpha.agent1", says(reason="SECRET reason text"), on)
    assert result.proposal is not None
    (entry,) = audits(db_session, world)
    assert entry.entity_id == on.id
    assert entry.changes == {"outcome": "proposed", "proposal_id": str(result.proposal.id)}
    assert "SECRET" not in str(entry.changes)


def test_no_change_needed_stores_no_proposal_but_is_still_audited(
    acting, db_session, world, on
) -> None:
    on.status = "contacted"
    db_session.flush()
    for model in (says("none", "Nothing to do."), says("contacted", "Same as now.")):
        db_session.expire_all()
        result = run(acting, "alpha.agent1", model, on, limits=lead_agent.Limits(10, 100))
        assert result.outcome == "no_suggestion" and result.proposal is None
    assert proposals(db_session, world) == [] and len(audits(db_session, world)) == 2


def test_the_model_never_sees_the_phone_or_the_address(acting, on) -> None:
    model = says()
    run(acting, "alpha.agent1", model, on)
    shown = model.calls[0]["system"]
    assert PHONE not in shown and EMAIL not in shown


@pytest.mark.parametrize(
    "arguments",
    [
        {"status": "converted", "reason": "Move to customer."},  # a person converts a lead
        {"status": "won", "reason": "Not a status."},
        {"status": "qualified"},  # reason missing
        {"status": "qualified", "reason": "ok", "owner_id": "x"},  # an extra field
        {"status": "qualified", "reason": 7},
    ],
)
def test_an_answer_that_is_not_exactly_ours_is_refused(
    acting, db_session, world, on, arguments
) -> None:
    with pytest.raises(lead_agent.SuggestionInvalidError):
        run(
            acting, "alpha.agent1", ScriptedModel(ToolUse("t1", "submit_suggestion", arguments)), on
        )
    assert proposals(db_session, world) == []


def test_two_calls_or_a_different_tool_are_refused(acting, db_session, world, on) -> None:
    good = ToolUse("t1", "submit_suggestion", {"status": "qualified", "reason": "ok"})
    for model in (ScriptedModel(good, good), ScriptedModel(ToolUse("t2", "approve", {}))):
        with pytest.raises(lead_agent.SuggestionInvalidError):
            run(acting, "alpha.agent1", model, on)
    assert proposals(db_session, world) == []


def test_a_link_in_the_reason_is_stopped_by_the_sentinel(acting, db_session, world, on) -> None:
    result = run(
        acting, "alpha.agent1", says(reason="See http://evil.example/steal for the proof."), on
    )
    assert result.outcome == "blocked" and result.proposal is None and result.blocked_message
    assert proposals(db_session, world) == []
    db_session.refresh(on)
    assert on.status == "new"


# --- it judges by the organisation's written steps ------------------------------------------


def test_the_model_is_shown_the_numbered_steps_as_data(acting, on) -> None:
    model = says()
    run(acting, "alpha.agent1", model, on)
    shown = model.calls[0]["system"]
    for number, step in enumerate(STEPS, start=1):
        assert f"{number}. {step}" in shown
    assert "steps" in shown.lower() and "not instructions" in shown


def test_without_written_steps_the_model_is_not_asked_and_nothing_is_stored(
    acting, db_session, world, lead
) -> None:
    configure(acting, enabled=True)  # switched on, but no procedure written
    model = says()
    with pytest.raises(NoActiveProcedureError):
        run(acting, "alpha.agent1", model, lead)
    assert model.calls == []
    assert proposals(db_session, world) == [] and audits(db_session, world) == []


def test_a_retired_procedure_counts_as_none(acting, db_session, world, on) -> None:
    from app.modules.qualifier import api as qualifier_api

    admin = acting.who("alpha.admin")
    current = qualifier_api.get_active(acting.session, admin)
    qualifier_api.deactivate(acting.session, admin, version=current.version)
    acting.session.flush()
    model = says()
    with pytest.raises(NoActiveProcedureError):
        run(acting, "alpha.agent1", model, on)
    assert model.calls == []


def test_another_organisations_steps_are_never_used(acting, db_session, world, lead) -> None:
    configure(acting, enabled=True)
    write_procedure(acting, "beta.admin", ["Another organisation's secret step."])
    model = says()
    with pytest.raises(NoActiveProcedureError):
        run(acting, "alpha.agent1", model, lead)
    assert model.calls == []


def test_switched_off_wins_over_a_missing_procedure(acting, lead) -> None:
    """An administrator who has not switched it on is told that first."""
    with pytest.raises(AgentUnavailableError):
        run(acting, "alpha.agent1", says(), lead)


# --- who may use it, and on which leads -------------------------------------------------------


@pytest.mark.parametrize("who", ["alpha.support", "alpha.customer"])
def test_roles_without_the_permission_are_refused(acting, on, who: str) -> None:
    model = says()
    with pytest.raises(ForbiddenError):
        run(acting, who, model, on)
    assert model.calls == []


def test_another_agents_lead_is_not_found_and_the_model_is_not_asked(acting, on) -> None:
    model = says()
    with pytest.raises(lead_agent.LeadNotFoundError):
        run(acting, "alpha.agent2", model, on)
    assert model.calls == []


def test_another_organisations_lead_is_not_found(acting, on) -> None:
    model = says()
    with pytest.raises(lead_agent.LeadNotFoundError):
        run(acting, "beta.agent", model, on)
    assert model.calls == []


def test_a_made_up_lead_is_not_found(acting, on) -> None:
    import uuid

    with pytest.raises(lead_agent.LeadNotFoundError):
        lead_agent.run_lead_agent(
            acting.session,
            acting.who("alpha.agent1"),
            says(),
            uuid.uuid4(),
            limits=LIMITS,
            ai_limits=AI,
        )


# --- limits -----------------------------------------------------------------------------------


def test_a_lead_is_looked_at_once_an_hour(acting, on) -> None:
    run(acting, "alpha.agent1", says("none", "Nothing."), on, limits=lead_agent.Limits(1, 100))
    model = says()
    with pytest.raises(lead_agent.RateLimitedError):
        run(acting, "alpha.agent1", model, on, limits=lead_agent.Limits(1, 100))
    assert model.calls == []


def test_an_organisation_has_a_daily_limit(acting, db_session, world, on) -> None:
    run(acting, "alpha.agent1", says("none", "Nothing."), on, limits=lead_agent.Limits(5, 1))
    other = add_lead(db_session, world, "alpha.agent1")
    with pytest.raises(lead_agent.RateLimitedError):
        run(acting, "alpha.agent1", says(), other, limits=lead_agent.Limits(5, 1))


def test_asking_twice_the_second_proposal_is_a_blocked_duplicate(
    acting, db_session, world, on
) -> None:
    open_limits = lead_agent.Limits(per_lead_hour=5, per_tenant_day=100)
    first = run(acting, "alpha.agent1", says(), on, limits=open_limits)
    second = run(acting, "alpha.agent1", says(), on, limits=open_limits)
    assert first.proposal is not None
    assert second.proposal is None and second.outcome == "blocked"
    assert len(proposals(db_session, world)) == 1


def test_a_blocked_proposal_is_audited_by_the_approvals_module(
    acting, db_session, world, on
) -> None:
    run(acting, "alpha.agent1", says(reason="Read https://evil.example/now first."), on)
    bind_tenant(db_session, alpha(world))
    blocked = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "agent_action.blocked")
    ).all()
    assert len(blocked) == 1


def test_the_per_lead_limit_holds_even_without_autoflush(acting, db_session, on) -> None:
    """The limit counts the audit rows of earlier runs; a caller whose session does not flush on
    its own (the evaluation command line, a worker) must still be limited (a bug found in LA5)."""
    with db_session.no_autoflush:
        run(acting, "alpha.agent1", says("none", "Nothing."), on, limits=lead_agent.Limits(1, 100))
        model = says()
        with pytest.raises(lead_agent.RateLimitedError):
            run(acting, "alpha.agent1", model, on, limits=lead_agent.Limits(1, 100))
    assert model.calls == []
