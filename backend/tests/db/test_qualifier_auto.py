# ruff: noqa: F811, F401, S608 - fixtures are imported and used as parameters
"""The automatic Qualifier for new website leads (docs/qualifier.md), off by default.

The event handler is tested directly (scripted model) and once through the real worker (the demo
model). Whatever happens, the Automation identity only SUGGESTS: a manager approves.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.events import Event, publish
from app.core.mail import MemoryMailer
from app.core.outbox import OutboxJob, PermanentJobError
from app.core.storage import MemoryFileStore
from app.modules.agents import api as agents_api
from app.modules.approvals import service as approvals_service
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import AssistantUnavailableError, ModelReply
from app.modules.identity.models import User
from app.modules.leads.models import Lead
from app.modules.qualifier import api as qualifier_api
from app.modules.qualifier.models import LeadAssessment
from app.worker import WorkerServices, job_handlers, run_due_jobs
from tests.db.conftest import forget_request_user, session_factory_for
from tests.db.test_approvals import Acting, acting, alpha
from tests.db.test_qualifier_assess import ScriptedModel, lead_with_details, says, write_procedure
from tests.db.test_qualifier_governed import AI, KEY, configure, make_settings, metered
from tests.db.test_quotes_api import World, world

NAME = "public_chat.lead_captured"


def event_for(world: World, lead_id: Any, *, tenant: uuid.UUID | None = None) -> Event:
    return Event(
        id=uuid.uuid4(),
        tenant_id=tenant or alpha(world),
        name=NAME,
        data={"lead_id": str(lead_id), "session_id": str(uuid.uuid4())},
        depth=0,
    )


def handler(model: Any, **settings: Any) -> Any:
    subscribers = qualifier_api.event_subscribers(
        make_settings(qualifier_auto_web_leads=True, **settings), lambda _: model
    )
    return subscribers[NAME][0]


def deliver(db_session: Session, world: World, model: Any, lead: Lead, **settings: Any) -> None:
    forget_request_user(db_session)  # like a real worker job: only the tenant is bound
    bind_tenant(db_session, alpha(world))
    handler(model, **settings)(db_session, event_for(world, lead.id))


def stored(db_session: Session, world: World, table: Any) -> list[Any]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(table)))


@pytest.fixture
def ready(acting: Acting, db_session: Session, world: World) -> Lead:
    lead = lead_with_details(db_session, world, owner="alpha.agent1")
    write_procedure(acting)
    return lead


# --- it is off unless switched on ------------------------------------------------


def test_it_is_off_by_default() -> None:
    assert make_settings().qualifier_auto_web_leads is False
    assert qualifier_api.event_subscribers(make_settings()) == {}


def test_when_on_it_listens_to_new_website_leads_only() -> None:
    subscribers = qualifier_api.event_subscribers(make_settings(qualifier_auto_web_leads=True))
    assert list(subscribers) == [NAME] and len(subscribers[NAME]) == 1


# --- what it does ------------------------------------------------


def test_a_new_website_lead_gets_a_proposal_from_the_automation_identity(
    acting, db_session, world, ready
) -> None:
    model = says()
    deliver(db_session, world, model, ready)
    (proposal,) = stored(db_session, world, AgentAction)
    (assessment,) = stored(db_session, world, LeadAssessment)
    automation = db_session.get(User, proposal.requested_by_user_id)
    assert automation is not None and automation.user_type == "automation"
    assert (proposal.agent, proposal.status, proposal.kind) == (
        "qualifier",
        "pending",
        "lead.set_status",
    )
    assert proposal.payload == {"status": "qualified"}
    assert assessment.requested_by_user_id == automation.id and assessment.outcome == "proposed"
    assert db_session.get(Lead, ready.id).status == "new"  # still only a suggestion
    assert len(model.calls) == 1


def test_any_manager_can_approve_it_and_only_then_the_lead_changes(
    acting, db_session, world, ready
) -> None:
    deliver(db_session, world, says(), ready)
    (proposal,) = stored(db_session, world, AgentAction)
    manager = acting.who("alpha.manager")
    done = approvals_service.approve(
        db_session, manager, proposal.id, version=proposal.version, note=None
    )
    assert done.status == "approved" and db_session.get(Lead, ready.id).status == "qualified"


def test_the_managers_hear_about_it_like_about_any_proposal(
    acting, db_session, world, ready
) -> None:
    deliver(db_session, world, says(), ready)
    jobs = [j.kind for j in stored(db_session, world, OutboxJob)]
    assert "event.agent_action.proposed" in jobs


def test_the_audit_names_the_automation_identity(acting, db_session, world, ready) -> None:
    deliver(db_session, world, says(), ready)
    (entry,) = [e for e in stored(db_session, world, AuditLog) if e.action == "qualifier.assessed"]
    automation = db_session.get(User, entry.actor_user_id)
    assert automation is not None and automation.display_name == "Automation"


# --- safe to run twice, and not twice for one lead ------------------------------------------------


def test_the_same_event_twice_assesses_once(acting, db_session, world, ready) -> None:
    model = says()
    deliver(db_session, world, model, ready)
    deliver(db_session, world, model, ready)
    assert len(model.calls) == 1
    assert len(stored(db_session, world, LeadAssessment)) == 1
    assert len(stored(db_session, world, AgentAction)) == 1


def test_a_lead_a_person_already_assessed_is_skipped(acting, db_session, world, ready) -> None:
    qualifier_api.assess_lead(
        db_session,
        acting.who("alpha.agent1"),
        says(decision="no_change", matched_steps=[]),
        ready.id,
    )
    model = says()
    deliver(db_session, world, model, ready)
    assert model.calls == [] and len(stored(db_session, world, LeadAssessment)) == 1


def test_a_lead_assessed_long_ago_is_still_skipped(acting, db_session, world, ready) -> None:
    """The per-lead hourly limit would not stop this: the skip is its own rule."""
    procedure = qualifier_api.get_active(db_session, acting.who("alpha.admin"))
    db_session.add(
        LeadAssessment(
            tenant_id=alpha(world),
            lead_id=ready.id,
            procedure_id=procedure.id,
            procedure_version=procedure.version,
            requested_by_user_id=world.users["alpha.agent1"].id,
            decision="no_change",
            matched_steps=[],
            reasons=["Older."],
            missing=[],
            fields_given=[],
            outcome="no_proposal",
            created_at=datetime.now(UTC) - timedelta(hours=3),
        )
    )
    db_session.flush()
    model = says()
    deliver(db_session, world, model, ready)
    assert model.calls == []


# --- business refusals finish quietly ------------------------------------------------


def test_without_a_procedure_nothing_is_asked(acting, db_session, world) -> None:
    lead = lead_with_details(db_session, world)
    model = says()
    deliver(db_session, world, model, lead)
    assert model.calls == [] and stored(db_session, world, AgentAction) == []


def test_a_switched_off_qualifier_does_nothing(acting, db_session, world, ready) -> None:
    configure(acting, enabled=False)
    model = says()
    deliver(db_session, world, model, ready)
    assert model.calls == [] and stored(db_session, world, LeadAssessment) == []


def test_an_exhausted_budget_does_nothing(acting, db_session, world, ready) -> None:
    agents_api.record_usage(
        db_session, alpha(world), KEY, input_tokens=10**9, output_tokens=0,
        limits=agents_api.Limits(False, 1000), now=datetime.now(UTC),
    )  # fmt: skip
    model = says()
    deliver(db_session, world, model, ready, ai_disabled=False, agent_default_monthly_tokens=1000)
    assert model.calls == []


def test_the_daily_limit_of_the_organisation_applies(acting, db_session, world, ready) -> None:
    other = lead_with_details(db_session, world)
    deliver(
        db_session,
        world,
        says(decision="no_change", matched_steps=[]),
        ready,
        qualifier_per_tenant_day=1,
    )
    model = says()
    deliver(db_session, world, model, other, qualifier_per_tenant_day=1)
    assert model.calls == [] and len(stored(db_session, world, LeadAssessment)) == 1


def test_an_unusable_answer_is_dropped_but_its_tokens_are_counted(
    acting, db_session, world, ready
) -> None:
    deliver(db_session, world, metered(decision="converted"), ready)
    assert stored(db_session, world, LeadAssessment) == []
    assert stored(db_session, world, AgentAction) == []
    state = agents_api.get_agent(db_session, acting.who("alpha.admin"), KEY, AI, datetime.now(UTC))
    assert state.calls == 1 and state.used_tokens == 500


def test_a_link_in_the_models_reasons_is_blocked_by_the_sentinel_as_ever(
    acting, db_session, world, ready
) -> None:
    deliver(db_session, world, says(reasons=["See https://evil.example/x"]), ready)
    (assessment,) = stored(db_session, world, LeadAssessment)
    assert assessment.outcome == "blocked" and stored(db_session, world, AgentAction) == []


# --- what is retried and what is not ------------------------------------------------


class Down:
    available = True

    def reply(self, **_: Any) -> ModelReply:
        raise AssistantUnavailableError("The assistant is temporarily unavailable.")


def test_a_model_that_is_down_is_retried_not_swallowed(acting, db_session, world, ready) -> None:
    with pytest.raises(AssistantUnavailableError):
        deliver(db_session, world, Down(), ready)


def test_an_event_without_a_lead_id_is_a_permanent_failure(
    acting, db_session, world, ready
) -> None:
    bind_tenant(db_session, alpha(world))
    bad = Event(uuid.uuid4(), alpha(world), NAME, {}, 0)
    with pytest.raises(PermanentJobError):
        handler(says())(db_session, bad)


def test_a_lead_of_another_organisation_is_not_assessed(acting, db_session, world, ready) -> None:
    beta = world.users["beta.agent"]
    from tests.db.conftest import setup_lead_context

    setup_lead_context(db_session, beta.tenant_id, beta.id)
    foreign = Lead(tenant_id=beta.tenant_id, last_name="Beta", owner_id=beta.id)
    db_session.add(foreign)
    db_session.flush()
    model = says()
    bind_tenant(db_session, alpha(world))
    handler(model)(db_session, event_for(world, foreign.id))
    assert model.calls == [] and stored(db_session, world, LeadAssessment) == []


# --- through the real worker ------------------------------------------------


def test_the_real_worker_runs_it_with_the_demo_model(
    acting, db_session, db_connection, world, ready
) -> None:
    settings = make_settings(qualifier_auto_web_leads=True, ai_provider="fake")
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, MemoryFileStore(), MemoryMailer()))
    bind_tenant(db_session, alpha(world))
    publish(
        db_session, alpha(world), NAME, {"lead_id": str(ready.id), "session_id": str(uuid.uuid4())}
    )
    db_session.flush()
    with factory() as fresh, fresh.begin():
        forget_request_user(fresh)  # like a real worker transaction
    run_due_jobs(factory, handlers, settings)
    (proposal,) = stored(db_session, world, AgentAction)
    assert proposal.agent == "qualifier" and proposal.status == "pending"
    assert proposal.payload == {"status": "qualified"}  # a phone and 1.2 crore: the demo rules


def test_the_real_worker_does_nothing_while_the_setting_is_off(
    acting, db_session, db_connection, world, ready
) -> None:
    settings = make_settings(ai_provider="fake")  # qualifier_auto_web_leads stays False
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, MemoryFileStore(), MemoryMailer()))
    bind_tenant(db_session, alpha(world))
    publish(
        db_session, alpha(world), NAME, {"lead_id": str(ready.id), "session_id": str(uuid.uuid4())}
    )
    db_session.flush()
    with factory() as fresh, fresh.begin():
        forget_request_user(fresh)
    run_due_jobs(factory, handlers, settings)
    assert stored(db_session, world, AgentAction) == []
    assert stored(db_session, world, LeadAssessment) == []
