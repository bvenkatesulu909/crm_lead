# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Approval queue (ADR 0014, step AP2) through the real API, events and the worker.

Proposals are made through the service (the staff assistant does that from step AP3 on); people
decide through the API. People come from test_quotes_api.py: tenant alpha has admin, manager,
manager2, agent1, agent2, support, customers; tenant beta has admin and agent.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import DomainError
from app.core.mail import MemoryMailer
from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.approvals import service
from app.modules.approvals.models import AgentAction
from app.modules.leads.models import Lead
from app.worker import WorkerServices, job_handlers, run_due_jobs, run_schedules
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import forget_request_user, session_factory_for, setup_lead_context
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import Headers, World, api, auth, ok, world  # noqa: F401

ACTIONS = "/api/v1/approvals/actions"
REASON = "The buyer confirmed their budget on the phone."


@pytest.fixture
def worker(db_connection: Connection) -> Any:
    settings = Settings(
        _env_file=None, database_url=UNREACHABLE_DATABASE_URL, oidc_issuer=TEST_ISSUER
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, MemoryFileStore(), MemoryMailer()))

    def run() -> int:
        with factory() as fresh, fresh.begin():
            forget_request_user(fresh)  # like a real worker transaction
        run_schedules(factory, settings)
        return run_due_jobs(factory, handlers, settings)

    return run


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.admin"].tenant_id


def add_lead(db_session: Session, world: World, owner: str = "alpha.agent1") -> Lead:
    setup_lead_context(db_session, alpha(world), world.users[owner].id)
    lead = Lead(
        tenant_id=alpha(world), first_name="Asha", last_name="Rao", owner_id=world.users[owner].id
    )
    db_session.add(lead)
    db_session.flush()
    return lead  # fmt: skip


def propose(
    db_session: Session, world: World, who: str, lead: Lead, status: str = "contacted", **extra: Any
) -> AgentAction:
    from tests.db.conftest import bind_principal

    principal = principal_for(world.users[who], ROLES[who])
    bind_principal(db_session, principal)
    action = service.propose(
        db_session,
        principal,
        kind="lead.set_status",
        target_id=lead.id,
        payload={"status": status},
        reason=REASON,
        agent="staff_assistant",
        **extra,
    )
    db_session.flush()  # like the request's commit: everything is written before the worker runs
    return action


def lead_status(db_session: Session, world: World, lead: Lead) -> str:
    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.refresh(lead)
    return lead.status


def titles(api: TestClient, auth: Headers, user: str) -> list[str]:
    return [n["title"] for n in ok(api.get("/api/v1/notifications", headers=auth(user)))["items"]]


# --- reading the queue ----------------------------------------------------------------------


def test_approvers_see_the_organisations_queue_and_others_only_their_own(
    api, auth, world, db_session
) -> None:
    lead1 = add_lead(db_session, world, "alpha.agent1")
    lead2 = add_lead(db_session, world, "alpha.agent2")
    first = propose(db_session, world, "alpha.agent1", lead1)
    propose(db_session, world, "alpha.agent2", lead2)

    page = ok(api.get(ACTIONS, headers=auth("alpha.manager")))
    assert page["total"] == 2
    item = next(i for i in page["items"] if i["id"] == str(first.id))
    assert item["description"] == "Change the lead's status to contacted"
    assert item["target_link"] == f"/leads/{lead1.id}"
    assert item["target_label"] == "Asha Rao"
    assert item["reason"] == REASON
    assert item["status"] == "pending" and item["version"] == 1
    assert item["requested_by_user_id"] == str(world.users["alpha.agent1"].id)

    own = ok(api.get(ACTIONS, headers=auth("alpha.agent1")))
    assert [i["id"] for i in own["items"]] == [str(first.id)]
    assert ok(api.get(ACTIONS, headers=auth("beta.admin")))["total"] == 0
    assert api.get(ACTIONS, headers=auth("alpha.customer")).status_code == 403
    assert api.get(ACTIONS).status_code == 401


def test_filters_run_in_the_database(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    decided = propose(db_session, world, "alpha.agent1", lead)
    propose(db_session, world, "alpha.manager", lead, "qualified")
    ok(
        api.post(
            f"{ACTIONS}/{decided.id}/reject",
            json={"version": 1, "note": "Not yet"},
            headers=auth("alpha.manager"),
        )
    )
    pending = ok(api.get(ACTIONS, params={"status": "pending"}, headers=auth("alpha.admin")))
    assert [i["status"] for i in pending["items"]] == ["pending"]
    mine = ok(api.get(ACTIONS, params={"mine": True}, headers=auth("alpha.manager")))
    assert [i["requested_by_user_id"] for i in mine["items"]] == [
        str(world.users["alpha.manager"].id)
    ]
    assert (
        api.get(ACTIONS, params={"status": "lost"}, headers=auth("alpha.admin")).status_code == 422
    )
    paged = ok(api.get(ACTIONS, params={"limit": 1}, headers=auth("alpha.admin")))
    assert (len(paged["items"]), paged["total"]) == (1, 2)


def test_proposals_of_one_record(api, auth, world, db_session) -> None:
    lead1 = add_lead(db_session, world, "alpha.agent1")
    lead2 = add_lead(db_session, world, "alpha.agent1")
    propose(db_session, world, "alpha.agent1", lead1)
    propose(db_session, world, "alpha.agent1", lead1, "qualified")
    propose(db_session, world, "alpha.agent1", lead2)

    page = ok(api.get(ACTIONS, params={"target_id": str(lead1.id)}, headers=auth("alpha.manager")))
    assert page["total"] == 2
    assert {i["target_id"] for i in page["items"]} == {str(lead1.id)}
    both = {"target_id": str(lead1.id), "status": "pending"}
    assert ok(api.get(ACTIONS, params=both, headers=auth("alpha.manager")))["total"] == 2
    # Others only ever see their own proposals, whatever they ask for.
    assert (
        ok(api.get(ACTIONS, params={"target_id": str(lead1.id)}, headers=auth("alpha.agent2")))[
            "total"
        ]
        == 0
    )
    other_tenant = {"target_id": str(lead1.id)}
    assert ok(api.get(ACTIONS, params=other_tenant, headers=auth("beta.admin")))["total"] == 0
    bad = api.get(ACTIONS, params={"target_id": "nope"}, headers=auth("alpha.manager"))
    assert bad.status_code == 422


def test_one_proposal(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    url = f"{ACTIONS}/{action.id}"
    assert ok(api.get(url, headers=auth("alpha.agent1")))["id"] == str(action.id)
    assert ok(api.get(url, headers=auth("alpha.manager")))["id"] == str(action.id)
    for other in ("alpha.agent2", "beta.admin"):
        assert api.get(url, headers=auth(other)).status_code == 404
    assert api.get(f"{ACTIONS}/{uuid.uuid4()}", headers=auth("alpha.manager")).status_code == 404
    assert api.get(f"{ACTIONS}/not-a-uuid", headers=auth("alpha.manager")).status_code == 422


# --- deciding -------------------------------------------------------------------------------


def test_a_manager_approves_through_the_api(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    url = f"{ACTIONS}/{action.id}/approve"

    assert api.post(url, json={"version": 1}, headers=auth("alpha.agent1")).status_code == 403
    assert api.post(url, json={"version": 1}, headers=auth("alpha.agent2")).status_code == 403
    assert api.post(url, json={"version": 1}, headers=auth("beta.admin")).status_code == 404
    stale = api.post(url, json={"version": 7}, headers=auth("alpha.manager"))
    assert (stale.status_code, stale.json()["code"]) == (409, "agent_action_changed")
    extra = api.post(url, json={"version": 1, "status": "approved"}, headers=auth("alpha.manager"))
    assert extra.status_code == 422  # nothing but version and note

    body = ok(api.post(url, json={"version": 1, "note": "Fine"}, headers=auth("alpha.manager")))
    assert (body["status"], body["decision_note"]) == ("approved", "Fine")
    assert body["decided_by_user_id"] == str(world.users["alpha.manager"].id)
    assert lead_status(db_session, world, lead) == "contacted"
    again = api.post(url, json={"version": body["version"]}, headers=auth("alpha.manager2"))
    assert (again.status_code, again.json()["code"]) == (409, "agent_action_already_decided")


def test_self_approval_is_refused_by_the_api(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world, "alpha.manager")
    action = propose(db_session, world, "alpha.manager", lead)
    refused = api.post(
        f"{ACTIONS}/{action.id}/approve", json={"version": 1}, headers=auth("alpha.manager")
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "self_approval_forbidden")


def test_a_rejection_through_the_api(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    url = f"{ACTIONS}/{action.id}/reject"
    empty = api.post(url, json={"version": 1, "note": " "}, headers=auth("alpha.manager"))
    assert empty.status_code == 422
    assert api.post(url, json={"version": 1}, headers=auth("alpha.manager")).status_code == 422
    body = ok(api.post(url, json={"version": 1, "note": "Call first"}, headers=auth("alpha.admin")))
    assert body["status"] == "rejected"
    assert lead_status(db_session, world, lead) == "new"


# --- events and notifications -----------------------------------------------------------------


def _event(db_session: Session, world: World, name: str) -> list[OutboxJob]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(OutboxJob).where(OutboxJob.kind == f"event.{name}")))


def test_events_carry_ids_only(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    [proposed] = _event(db_session, world, "agent_action.proposed")
    assert proposed.payload["data"] == {
        "action_id": str(action.id),
        "actor_id": str(world.users["alpha.agent1"].id),
    }
    ok(
        api.post(
            f"{ACTIONS}/{action.id}/approve", json={"version": 1}, headers=auth("alpha.manager")
        )
    )
    [decided] = _event(db_session, world, "agent_action.decided")
    assert decided.payload["data"] == {
        "action_id": str(action.id),
        "actor_id": str(world.users["alpha.manager"].id),
    }  # fmt: skip


def test_approvers_hear_about_proposals_and_the_requester_about_the_decision(
    api, auth, world, worker, db_session
) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    worker()
    waiting = "AI proposal waiting for approval: Change the lead's status to contacted"
    for approver in ("alpha.manager", "alpha.manager2", "alpha.admin"):
        assert titles(api, auth, approver) == [waiting], approver
    for other in ("alpha.agent1", "alpha.agent2", "alpha.support", "beta.admin"):
        assert titles(api, auth, other) == [], other

    ok(
        api.post(
            f"{ACTIONS}/{action.id}/approve", json={"version": 1}, headers=auth("alpha.manager")
        )
    )
    worker()
    assert titles(api, auth, "alpha.agent1") == [
        "Your AI proposal was approved: Change the lead's status to contacted"
    ]
    assert waiting in titles(api, auth, "alpha.manager2")  # the old note stays, nothing new
    assert len(titles(api, auth, "alpha.manager")) == 1  # the decider isn't told about it


def test_a_managers_own_proposal_is_not_announced_to_them(api, auth, world, worker, db_session):
    lead = add_lead(db_session, world, "alpha.manager")
    propose(db_session, world, "alpha.manager", lead)
    worker()
    assert titles(api, auth, "alpha.manager") == []
    assert len(titles(api, auth, "alpha.manager2")) == 1


# --- expiry and the pending limit ------------------------------------------------------------


def test_the_worker_expires_old_proposals_and_tells_the_requester(
    api, auth, world, worker, db_session
) -> None:
    lead = add_lead(db_session, world)
    old = propose(db_session, world, "alpha.agent1", lead)
    fresh = propose(db_session, world, "alpha.agent1", lead, "qualified")
    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(AgentAction)
        .where(AgentAction.id == old.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    worker()
    bind_tenant(db_session, alpha(world))
    db_session.refresh(old)
    db_session.refresh(fresh)
    assert (old.status, fresh.status) == ("expired", "pending")
    assert old.decided_at is not None and old.decided_by_user_id is None
    assert "Your AI proposal expired: Change the lead's status to contacted" in titles(
        api, auth, "alpha.agent1"
    )
    worker()  # a second run changes nothing and tells nobody twice
    assert (
        titles(api, auth, "alpha.agent1").count(
            "Your AI proposal expired: Change the lead's status to contacted"
        )
        == 1
    )


def test_one_person_can_have_only_a_few_proposals_waiting(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    first = propose(db_session, world, "alpha.agent1", lead, pending_limit=2)
    propose(db_session, world, "alpha.agent1", lead, "qualified", pending_limit=2)
    with pytest.raises(DomainError) as full:
        propose(db_session, world, "alpha.agent1", lead, "unqualified", pending_limit=2)
    assert (full.value.status_code, full.value.code) == (429, "agent_action_limit_reached")
    # Decided proposals don't count; other people have their own limit.
    ok(
        api.post(
            f"{ACTIONS}/{first.id}/reject",
            json={"version": 1, "note": "No"},
            headers=auth("alpha.manager"),
        )
    )
    propose(db_session, world, "alpha.agent1", lead, "unqualified", pending_limit=2)
    propose(db_session, world, "alpha.manager", lead, "qualified", pending_limit=2)


def test_the_settings_have_safe_defaults() -> None:
    base: dict[str, Any] = {"database_url": UNREACHABLE_DATABASE_URL, "oidc_issuer": TEST_ISSUER}
    settings = Settings(_env_file=None, **base)
    assert (settings.agent_action_expiry_days, settings.agent_action_pending_per_user) == (7, 20)
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_action_expiry_days=0, **base)
