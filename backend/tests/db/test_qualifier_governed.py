# ruff: noqa: F811, F401, S608 - fixtures are imported and used as parameters
"""The Qualifier under the agent registry, with limits, audit and metrics (QA3).

The switch, the monthly budget, the tool filter and the platform switch of ADR 0016 apply to it
like to every AI feature; assessments are rate-limited per lead, per person and per
organisation; each one is audited (ids and codes only) and counted without a tenant label.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.observability.metrics import QUALIFIER_ASSESSMENTS, QUALIFIER_REFUSALS, REGISTRY
from app.modules.agents import api as agents_api
from app.modules.agents.service import AgentBudgetReachedError, AgentUnavailableError
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ModelReply
from app.modules.leads.models import Lead
from app.modules.qualifier import api as qualifier_api
from app.modules.qualifier.fake import FakeQualifierModel
from app.modules.qualifier.models import LeadAssessment
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.test_approvals import Acting, acting, add_lead, alpha
from tests.db.test_qualifier_assess import (
    ScriptedModel,
    lead_with_details,
    says,
    write_procedure,
)
from tests.db.test_quotes_api import World, world


def make_settings(**changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        environment=changes.pop("environment", "test"),
        database_url=UNREACHABLE_DATABASE_URL,
        **({"oidc_issuer": TEST_ISSUER} | changes),
    )


AI = agents_api.Limits(platform_disabled=False, default_monthly_tokens=1000)
KEY = "qualifier"
NOW = datetime.now(UTC)


class Metered(ScriptedModel):
    """Reports the tokens it used, like a real provider."""

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        base = super().reply(system=system, messages=messages, tools=tools)
        return ModelReply(
            base.text, tool_uses=base.tool_uses, usage={"input_tokens": 400, "output_tokens": 100}
        )


def metered(**values: Any) -> Metered:
    plain = says(**values)
    return Metered(*plain.uses)


def run(
    acting: Acting,
    who: str,
    model: Any,
    lead: Lead,
    *,
    limits: qualifier_api.Limits | None = None,
    ai: agents_api.Limits = AI,
    now: datetime | None = None,
) -> qualifier_api.AssessmentResult:
    return qualifier_api.assess_lead(
        acting.session,
        acting.who(who),
        model,
        lead.id,
        limits=limits or qualifier_api.Limits(5, 20, 300),
        ai_limits=ai,
        now=now,
    )


def configure(acting: Acting, **changes: Any) -> None:
    principal = acting.who("alpha.admin")
    current = agents_api.get_agent(acting.session, principal, KEY, AI, NOW)
    kwargs: dict[str, Any] = dict(changes)
    if current.version is not None:
        kwargs["version"] = current.version
    agents_api.update_settings(acting.session, principal, KEY, limits=AI, now=NOW, **kwargs)
    acting.session.flush()


def sample(counter: Any, **labels: str) -> float:
    return REGISTRY.get_sample_value(counter._name + "_total", labels) or 0.0


@pytest.fixture
def ready(acting: Acting, db_session: Session, world: World) -> Lead:
    lead = lead_with_details(db_session, world)
    write_procedure(acting)
    return lead


# --- it is an agent of the registry ------------------------------------------------


def test_the_qualifier_is_listed_with_its_one_tool_and_starts_on(acting, ready) -> None:
    state = agents_api.get_agent(acting.session, acting.who("alpha.admin"), KEY, AI, NOW)
    assert state.enabled is True and state.agent.uses_model is True
    assert state.agent.tools == ("submit_assessment",) and state.agent.default_enabled is True


def test_a_switched_off_qualifier_never_reaches_the_model_and_proposes_nothing(
    acting, db_session, world, ready
) -> None:
    configure(acting, enabled=False)
    model = says()
    with pytest.raises(AgentUnavailableError):
        run(acting, "alpha.agent1", model, ready)
    assert model.calls == []
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(AgentAction)).all() == []
    assert db_session.scalars(select(LeadAssessment)).all() == []


def test_the_platform_switch_stops_it(acting, ready) -> None:
    model = says()
    with pytest.raises(AgentUnavailableError):
        run(acting, "alpha.agent1", model, ready, ai=agents_api.Limits(True, 1000))
    assert model.calls == []


def test_over_budget_stops_it_before_the_model(acting, db_session, world, ready) -> None:
    agents_api.record_usage(
        db_session, alpha(world), KEY, input_tokens=1000, output_tokens=0, limits=AI, now=NOW
    )
    model = says()
    with pytest.raises(AgentBudgetReachedError):
        run(acting, "alpha.agent1", model, ready)
    assert model.calls == []


def test_the_tokens_of_an_assessment_are_counted(acting, db_session, world, ready) -> None:
    run(acting, "alpha.agent1", metered(), ready)
    state = agents_api.get_agent(acting.session, acting.who("alpha.admin"), KEY, AI, NOW)
    assert (state.input_tokens, state.output_tokens, state.calls) == (400, 100, 1)


def test_taking_the_tool_away_leaves_the_model_nothing_to_report_with(
    acting, db_session, world, ready
) -> None:
    configure(acting, allowed_tools=[])
    model = says()
    with pytest.raises(qualifier_api.AssessmentInvalidError):
        run(acting, "alpha.agent1", model, ready)
    assert model.calls[0]["tools"] == []  # nothing was offered
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(AgentAction)).all() == []


def test_another_organisations_switch_does_not_matter(acting, db_session, world, ready) -> None:
    beta = acting.who("beta.admin")
    agents_api.update_settings(db_session, beta, KEY, limits=AI, now=NOW, enabled=False)
    assert run(acting, "alpha.agent1", says(), ready).proposal is not None


# --- limits ------------------------------------------------


def test_a_lead_can_be_assessed_once_an_hour(acting, db_session, world, ready) -> None:
    limits = qualifier_api.Limits(per_lead_hour=1, per_user_hour=20, per_tenant_day=300)
    run(acting, "alpha.agent1", says(decision="no_change", matched_steps=[]), ready, limits=limits)
    model = says()
    with pytest.raises(qualifier_api.RateLimitedError) as caught:
        run(acting, "alpha.agent1", model, ready, limits=limits)
    assert caught.value.status_code == 429 and model.calls == []
    # An hour and a bit later it may be assessed again.
    later = datetime.now(UTC) + timedelta(hours=1, minutes=5)
    run(
        acting,
        "alpha.agent1",
        says(decision="no_change", matched_steps=[]),
        ready,
        limits=limits,
        now=later,
    )


def test_a_person_has_an_hourly_limit_that_others_do_not_share(
    acting, db_session, world, ready
) -> None:
    limits = qualifier_api.Limits(per_lead_hour=5, per_user_hour=1, per_tenant_day=300)
    other = lead_with_details(db_session, world)
    run(acting, "alpha.agent1", says(decision="no_change", matched_steps=[]), ready, limits=limits)
    with pytest.raises(qualifier_api.RateLimitedError):
        run(acting, "alpha.agent1", says(), other, limits=limits)
    assert run(acting, "alpha.manager", says(), other, limits=limits).proposal is not None


def test_an_organisation_has_a_daily_limit_that_another_does_not_share(
    acting, db_session, world, ready
) -> None:
    limits = qualifier_api.Limits(per_lead_hour=5, per_user_hour=20, per_tenant_day=1)
    other = lead_with_details(db_session, world)
    run(acting, "alpha.agent1", says(decision="no_change", matched_steps=[]), ready, limits=limits)
    with pytest.raises(qualifier_api.RateLimitedError):
        run(acting, "alpha.manager", says(), other, limits=limits)
    with pytest.raises(qualifier_api.RateLimitedError):  # twelve hours later it still counts
        run(
            acting,
            "alpha.manager",
            says(),
            other,
            limits=limits,
            now=datetime.now(UTC) + timedelta(hours=12),
        )
    run(
        acting, "alpha.manager", says(decision="no_change", matched_steps=[]), other,
        limits=limits, now=datetime.now(UTC) + timedelta(days=1, minutes=1),
    )  # fmt: skip


def test_a_refused_answer_does_not_use_up_the_limit(acting, db_session, world, ready) -> None:
    limits = qualifier_api.Limits(per_lead_hour=1, per_user_hour=20, per_tenant_day=300)
    with pytest.raises(qualifier_api.AssessmentInvalidError):
        run(acting, "alpha.agent1", says(decision="converted"), ready, limits=limits)
    assert run(acting, "alpha.agent1", says(), ready, limits=limits).proposal is not None


def test_the_limits_come_from_the_settings() -> None:
    settings = make_settings(
        qualifier_per_lead_hour=2,
        qualifier_per_user_hour=3,
        qualifier_per_tenant_day=4,
    )
    assert qualifier_api.Limits.from_settings(settings) == qualifier_api.Limits(2, 3, 4)
    assert qualifier_api.Limits.default() == qualifier_api.Limits(1, 20, 300)


# --- audit and metrics ------------------------------------------------


def test_each_assessment_is_audited_with_ids_and_codes_only(
    acting, db_session, world, ready
) -> None:
    result = run(acting, "alpha.agent1", says(reasons=["Secret reasoning about Asha"]), ready)
    bind_tenant(db_session, alpha(world))
    (entry,) = db_session.scalars(select(AuditLog).where(AuditLog.action == "qualifier.assessed"))
    assert entry.entity_type == "lead" and entry.entity_id == ready.id
    assert entry.actor_user_id == world.users["alpha.agent1"].id
    assert entry.changes == {
        "assessment_id": str(result.assessment.id),
        "decision": "qualify",
        "outcome": "proposed",
        "procedure_version": 1,
        "proposal_id": str(result.proposal.id) if result.proposal else None,
    }
    assert "Secret reasoning" not in str(entry.changes)


def test_a_refused_request_leaves_no_assessment_audit_entry(
    acting, db_session, world, ready
) -> None:
    with pytest.raises(qualifier_api.AssessmentInvalidError):
        run(acting, "alpha.agent1", says(decision="converted"), ready)
    bind_tenant(db_session, alpha(world))
    assert (
        db_session.scalars(select(AuditLog).where(AuditLog.action == "qualifier.assessed")).all()
        == []
    )


def test_assessments_and_refusals_are_counted_without_a_tenant(
    acting, db_session, world, ready
) -> None:
    before = sample(QUALIFIER_ASSESSMENTS, decision="qualify", outcome="proposed")
    run(acting, "alpha.agent1", says(), ready)
    assert sample(QUALIFIER_ASSESSMENTS, decision="qualify", outcome="proposed") == before + 1
    invalid = sample(QUALIFIER_REFUSALS, reason="invalid_answer")
    with pytest.raises(qualifier_api.AssessmentInvalidError):
        run(acting, "alpha.manager", says(decision="converted"), ready)
    assert sample(QUALIFIER_REFUSALS, reason="invalid_answer") == invalid + 1
    limited = sample(QUALIFIER_REFUSALS, reason="lead_limit")
    with pytest.raises(qualifier_api.RateLimitedError):
        run(acting, "alpha.agent1", says(), ready, limits=qualifier_api.Limits(1, 20, 300))
    assert sample(QUALIFIER_REFUSALS, reason="lead_limit") == limited + 1
    labels = {name for family in REGISTRY.collect() if family.name.startswith("crm_qualifier")
              for s in family.samples for name in s.labels}  # fmt: skip
    assert labels <= {"decision", "outcome", "reason"}  # never a tenant, lead or person


def test_no_procedure_is_counted_as_a_refusal(acting, db_session, world) -> None:
    lead = lead_with_details(db_session, world)
    before = sample(QUALIFIER_REFUSALS, reason="no_procedure")
    with pytest.raises(qualifier_api.NoActiveProcedureError):
        run(acting, "alpha.agent1", says(), lead)
    assert sample(QUALIFIER_REFUSALS, reason="no_procedure") == before + 1


# --- the scripted model for demos and tests ------------------------------------------------


@pytest.mark.parametrize(
    ("phone", "budget", "decision", "status"),
    [
        (True, 12_000_000, "qualify", "qualified"),
        (True, 1_000_000, "unqualify", "unqualified"),
        (True, 5_000_000, "contact_first", "contacted"),
        (False, 12_000_000, "need_info", None),
    ],
)
def test_the_fake_model_decides_by_visible_rules(
    acting, db_session, world, ready, phone: bool, budget: int, decision: str, status: str | None
) -> None:
    ready.phone = "+91 98765 43210" if phone else None
    ready.budget_min_inr, ready.budget_max_inr = budget, budget + 1
    db_session.flush()
    result = run(acting, "alpha.agent1", FakeQualifierModel(), ready)
    assert result.assessment.decision == decision and result.proposal is not None
    if status:
        assert result.proposal.payload == {"status": status}
    else:
        assert result.proposal.kind == "activity.create_task"
    assert db_session.get(Lead, ready.id).status == "new"  # still only a suggestion


def test_the_model_for_the_fake_provider_is_the_scripted_one() -> None:
    fake = make_settings(ai_provider="fake")
    assert isinstance(qualifier_api.model_for(fake), FakeQualifierModel)
    real = make_settings(ai_provider="deepseek")
    assert not isinstance(qualifier_api.model_for(real), FakeQualifierModel)


def test_the_fake_provider_can_never_run_in_production() -> None:
    with pytest.raises(ValueError, match="fake assistant provider"):
        make_settings(
            environment="production",
            oidc_issuer="https://auth.example.test/realms/crm",
            files_s3_secure=True,
            ai_provider="fake",
        )
