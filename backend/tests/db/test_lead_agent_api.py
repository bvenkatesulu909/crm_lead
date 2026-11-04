# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""The lead agent through the real API (ADR 0022, step LA4) and its automatic trigger.

Real application, real database, the real agent registry and approvals; only the model is a
scripted one that the test puts on the app (or the worker's model factory).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.events import Event
from app.modules.agents import api as agents_api
from app.modules.approvals.models import AgentAction
from app.modules.identity.models import User
from app.modules.lead_agent import api as lead_agent
from app.modules.lead_agent.llm import FakeLeadAgentModel
from app.modules.leads.models import Lead
from tests.db.conftest import forget_request_user
from tests.db.test_approvals import add_lead, alpha
from tests.db.test_lead_agent import says
from tests.db.test_qualifier_assess import ScriptedModel, lead_with_details
from tests.db.test_qualifier_governed import make_settings
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world

URL = "/api/v1/lead-agent/runs"
NAME = "public_chat.lead_captured"


def use(api: Any, model: Any) -> Any:
    api.app.state.lead_agent_model = model
    return model


def switch_on(api: Any, auth: Headers) -> None:
    current = ok(api.get("/api/v1/agents/lead_agent", headers=auth("alpha.admin")))
    body: dict[str, Any] = {"enabled": True}
    if current.get("version") is not None:
        body["version"] = current["version"]
    ok(api.patch("/api/v1/agents/lead_agent", json=body, headers=auth("alpha.admin")))


def ask(api: Any, auth: Headers, who: str, lead_id: Any) -> Any:
    return api.post(URL, json={"lead_id": str(lead_id)}, headers=auth(who))


@pytest.fixture
def ready(api, auth, world, db_session) -> Lead:
    switch_on(api, auth)
    return lead_with_details(db_session, world)


# --- asking ------------------------------------------------------------------------------------


def test_an_agent_asks_about_their_lead_and_a_proposal_waits(
    api, auth, world, db_session, ready
) -> None:
    model = use(api, says("qualified"))
    body = ok(ask(api, auth, "alpha.agent1", ready.id), 201)
    assert body["outcome"] == "proposed" and body["blocked_message"] is None
    assert body["proposal_link"] == f"/approvals/{body['proposal_id']}"
    assert len(model.calls) == 1
    assert db_session.get(Lead, ready.id).status == "new"  # only a suggestion
    action = ok(
        api.get(f"/api/v1/approvals/actions/{body['proposal_id']}", headers=auth("alpha.manager"))
    )
    assert action["agent"] == "lead_agent" and action["status"] == "pending"
    assert action["payload"] == {"status": "qualified"}


def test_no_suggestion_has_no_proposal(api, auth, ready) -> None:
    use(api, says("none", "Nothing."))
    body = ok(ask(api, auth, "alpha.agent1", ready.id), 201)
    assert (body["outcome"], body["proposal_id"], body["proposal_link"]) == (
        "no_suggestion",
        None,
        None,
    )


def test_a_link_in_the_reason_is_blocked_with_plain_words(api, auth, ready) -> None:
    use(api, says(reason="Read https://evil.example/now first."))
    body = ok(ask(api, auth, "alpha.agent1", ready.id), 201)
    assert body["outcome"] == "blocked" and body["proposal_id"] is None
    assert body["blocked_message"] and "evil.example" not in body["blocked_message"]


def test_the_agent_starts_off(api, auth, world, db_session) -> None:
    lead = lead_with_details(db_session, world)
    model = use(api, says())
    response = ask(api, auth, "alpha.agent1", lead.id)
    assert code_of(response) == (503, "agent_unavailable") and model.calls == []


# --- who may ask, and for which lead ------------------------------------------------------------


def test_roles_without_the_permission_are_refused(api, auth, ready) -> None:
    use(api, says())
    assert ask(api, auth, "alpha.support", ready.id).status_code == 403
    assert ask(api, auth, "alpha.customer", ready.id).status_code == 403


def test_without_a_token_it_is_401(api, ready) -> None:
    assert api.post(URL, json={"lead_id": str(ready.id)}).status_code == 401


def test_another_agents_lead_another_organisation_and_a_made_up_id_are_all_404(
    api, auth, ready
) -> None:
    model = use(api, says())
    for who, lead_id in (
        ("alpha.agent2", ready.id),
        ("beta.agent", ready.id),
        ("alpha.agent1", uuid.uuid4()),
    ):
        assert code_of(ask(api, auth, who, lead_id)) == (404, "lead_not_found")
    assert model.calls == []


@pytest.mark.parametrize(
    "extra", [{"tenant_id": str(uuid.uuid4())}, {"status": "qualified"}, {"owner_id": "x"}]
)
def test_the_body_takes_a_lead_id_and_nothing_else(api, auth, ready, extra) -> None:
    use(api, says())
    response = api.post(URL, json={"lead_id": str(ready.id), **extra}, headers=auth("alpha.agent1"))
    assert response.status_code == 422


def test_a_bad_model_answer_is_422_and_stores_nothing(api, auth, world, db_session, ready) -> None:
    use(api, says("converted", "Make them a customer."))
    assert code_of(ask(api, auth, "alpha.agent1", ready.id)) == (422, "lead_agent_invalid_answer")
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(AgentAction)).all() == []


def test_asking_twice_in_an_hour_is_429(api, auth, ready) -> None:
    use(api, says("none", "Nothing."))
    ok(ask(api, auth, "alpha.agent1", ready.id), 201)
    assert code_of(ask(api, auth, "alpha.agent1", ready.id)) == (429, "lead_agent_rate_limited")


def test_the_scripted_demo_model_gives_a_sensible_answer(api, auth, ready) -> None:
    use(api, FakeLeadAgentModel())
    body = ok(ask(api, auth, "alpha.agent1", ready.id), 201)
    assert body["outcome"] == "proposed"  # a new lead with a phone number: call first
    action = ok(
        api.get(f"/api/v1/approvals/actions/{body['proposal_id']}", headers=auth("alpha.manager"))
    )
    assert action["payload"] == {"status": "contacted"}


# --- the automatic trigger -----------------------------------------------------------------------


def handler(model: Any, **settings: Any) -> Any:
    subscribers = lead_agent.event_subscribers(
        make_settings(lead_agent_auto_web_leads=True, **settings), lambda _: model
    )
    return subscribers[NAME][0]


def deliver(db_session: Session, world: World, model: Any, lead: Lead) -> None:
    forget_request_user(db_session)  # like a real worker job: only the tenant is bound
    bind_tenant(db_session, alpha(world))
    event = Event(
        id=uuid.uuid4(),
        tenant_id=alpha(world),
        name=NAME,
        data={"lead_id": str(lead.id), "session_id": str(uuid.uuid4())},
        depth=0,
    )
    handler(model)(db_session, event)


def proposals(db_session: Session, world: World) -> list[AgentAction]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(AgentAction)))


def test_the_automatic_trigger_is_off_by_default() -> None:
    assert make_settings().lead_agent_auto_web_leads is False
    assert lead_agent.event_subscribers(make_settings()) == {}


def test_when_on_it_listens_to_new_website_leads_only() -> None:
    subscribers = lead_agent.event_subscribers(make_settings(lead_agent_auto_web_leads=True))
    assert list(subscribers) == [NAME] and len(subscribers[NAME]) == 1


def test_a_new_website_lead_gets_a_proposal_from_the_automation_identity(
    api, auth, world, db_session, ready
) -> None:
    model = says("qualified")
    deliver(db_session, world, model, ready)
    (proposal,) = proposals(db_session, world)
    automation = db_session.get(User, proposal.requested_by_user_id)
    assert automation is not None and automation.user_type == "automation"
    assert (proposal.agent, proposal.status) == ("lead_agent", "pending")
    assert db_session.get(Lead, ready.id).status == "new"  # still only a suggestion


def test_the_same_event_twice_looks_at_the_lead_once(api, auth, world, db_session, ready) -> None:
    model = says("qualified")
    deliver(db_session, world, model, ready)
    deliver(db_session, world, model, ready)
    assert len(model.calls) == 1 and len(proposals(db_session, world)) == 1


def test_a_lead_a_person_already_asked_about_is_skipped(
    api, auth, world, db_session, ready
) -> None:
    use(api, says("none", "Nothing."))
    ok(ask(api, auth, "alpha.agent1", ready.id), 201)
    model = says("qualified")
    deliver(db_session, world, model, ready)
    assert model.calls == []


def test_a_switched_off_agent_does_nothing_quietly(api, auth, world, db_session) -> None:
    lead = lead_with_details(db_session, world)  # the agent was never switched on
    model = says("qualified")
    deliver(db_session, world, model, lead)
    assert model.calls == [] and proposals(db_session, world) == []


def test_a_lead_looked_at_long_ago_is_still_skipped(api, auth, world, db_session, ready) -> None:
    """The per-lead hourly limit would not stop this: the skip is its own rule."""
    bind_tenant(db_session, alpha(world))
    db_session.add(
        AuditLog(
            tenant_id=alpha(world),
            actor_subject="test-subject",
            action="lead_agent.ran",
            entity_type="lead",
            entity_id=ready.id,
            changes={"outcome": "no_suggestion", "proposal_id": None},
            occurred_at=datetime.now(UTC) - timedelta(hours=3),
        )
    )
    db_session.flush()
    model = says("qualified")
    deliver(db_session, world, model, ready)
    assert model.calls == []
