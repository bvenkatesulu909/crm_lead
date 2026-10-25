# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Public website chat (ADR 0013, step PC4): what happens after a lead was saved.

Sales managers are told (event public_chat.lead_captured -> notification), staff who may see the
lead read the conversation on the lead page, and conversations that never became a lead are
deleted by the worker after 30 days. People come from test_quotes_api.py: tenant alpha has
admin, manager, manager2, agent1, agent2, support, customers; tenant beta has admin and agent.
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
from app.core.mail import MemoryMailer
from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.leads.models import Lead
from app.modules.public_chat.models import PublicChatMessage, PublicChatSession
from app.worker import WorkerServices, job_handlers, run_due_jobs, run_schedules
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import forget_request_user, session_factory_for, setup_lead_context
from tests.db.test_public_chat_api import PHONE_MESSAGE, alpha, chat, make_api  # noqa: F401
from tests.db.test_quotes_api import Headers, World, auth, ok, world  # noqa: F401
from tests.test_public_chat_rules import settings

NOTES = "/api/v1/notifications"
EVENT = "event.public_chat.lead_captured"


def transcript_url(lead_id: Any) -> str:
    return f"/api/v1/public-chat/leads/{lead_id}/transcript"


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


def saved_lead(api: TestClient, db_session: Session, world: World) -> uuid.UUID:
    """A visitor leaves their details; returns the new lead's id."""
    assert chat(api, PHONE_MESSAGE).json()["lead_saved"] is True
    bind_tenant(db_session, alpha(world))
    lead_id = db_session.scalars(
        select(PublicChatSession.lead_id).where(PublicChatSession.lead_id.is_not(None))
    ).one()
    assert lead_id is not None
    return lead_id


def titles(api: TestClient, auth: Headers, user: str) -> list[str]:
    body = ok(api.get(NOTES, headers=auth(user)))
    return [n["title"] for n in body["items"]]


# --- the event and the notification ---------------------------------------------------------


def test_a_saved_lead_publishes_an_event_with_ids_only(make_api, world, db_session) -> None:
    lead_id = saved_lead(make_api(), db_session, world)
    [job] = db_session.scalars(select(OutboxJob).where(OutboxJob.kind == EVENT)).all()
    conversation = db_session.scalars(select(PublicChatSession)).one()
    assert job.payload["data"] == {"lead_id": str(lead_id), "session_id": str(conversation.id)}


def test_a_conversation_without_details_publishes_nothing(make_api, world, db_session) -> None:
    chat(make_api(), "Hi, I want a flat")
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(OutboxJob).where(OutboxJob.kind == EVENT)).all() == []


def test_sales_managers_are_told_about_a_website_lead(
    make_api, auth, world, worker, db_session
) -> None:
    api = make_api()
    lead_id = saved_lead(api, db_session, world)
    worker()
    for manager in ("alpha.manager", "alpha.manager2"):
        body = ok(api.get(NOTES, headers=auth(manager)))
        [note] = body["items"]
        assert note["title"] == "New lead from the website chat: Suresh Kumar"
        assert note["link"] == f"/leads/{lead_id}"
    # Only sales managers: not agents, support, the admin or another organisation.
    for other in ("alpha.agent1", "alpha.agent2", "alpha.support", "alpha.admin", "beta.admin"):
        assert titles(api, auth, other) == [], other


def test_the_notification_is_made_once_even_if_the_worker_runs_again(
    make_api, auth, world, worker, db_session
) -> None:
    api = make_api()
    saved_lead(api, db_session, world)
    worker()
    bind_tenant(db_session, alpha(world))
    db_session.execute(  # the job is delivered a second time (e.g. after a crash)
        update(OutboxJob).where(OutboxJob.kind == EVENT).values(status="pending", attempts=0)
    )
    worker()
    assert len(titles(api, auth, "alpha.manager")) == 1


# --- the transcript on the lead page ----------------------------------------------------------


def test_a_manager_reads_the_conversation_of_a_website_lead(
    make_api, auth, world, db_session
) -> None:
    api = make_api()
    first = chat(api, "Hello").json()
    chat(api, PHONE_MESSAGE, token=first["token"])
    bind_tenant(db_session, alpha(world))
    lead_id = db_session.scalars(select(PublicChatSession.lead_id)).one()

    body = ok(api.get(transcript_url(lead_id), headers=auth("alpha.manager")))
    assert set(body) == {"started_at", "messages"}
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["visitor", "assistant", "visitor", "assistant"]
    assert body["messages"][0]["content"] == "Hello"
    assert body["messages"][2]["content"] == PHONE_MESSAGE
    assert set(body["messages"][0]) == {"role", "content", "created_at"}  # no ids or hashes
    assert body["started_at"] is not None


def test_only_staff_who_may_see_the_lead_read_its_conversation(
    make_api, auth, world, db_session
) -> None:
    api = make_api()
    lead_id = saved_lead(api, db_session, world)
    url = transcript_url(lead_id)
    # The lead has no owner yet: an agent may not see it - 404, as if it didn't exist.
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 404
    assert api.get(url, headers=auth("beta.admin")).status_code == 404  # another organisation
    assert api.get(url, headers=auth("alpha.customer")).status_code == 403  # portal user
    assert api.get(url, headers=auth("alpha.support")).status_code == 403  # no lead access
    assert api.get(url).status_code == 401

    # Once the lead is assigned to agent1, agent1 reads it.
    ok(
        api.post(
            f"/api/v1/leads/{lead_id}/assign",
            json={"owner_id": str(world.users["alpha.agent1"].id)},
            headers=auth("alpha.manager"),
        )
    )
    assert len(ok(api.get(url, headers=auth("alpha.agent1")))["messages"]) == 2
    assert api.get(url, headers=auth("alpha.agent2")).status_code == 404


def test_unknown_leads_and_leads_without_a_chat(make_api, auth, world, db_session) -> None:
    api = make_api()
    assert api.get(transcript_url(uuid.uuid4()), headers=auth("alpha.manager")).status_code == 404
    assert api.get(transcript_url("not-a-uuid"), headers=auth("alpha.manager")).status_code == 422
    setup_lead_context(db_session, alpha(world), world.users["alpha.manager"].id)
    manager = world.users["alpha.manager"].id
    lead = Lead(tenant_id=alpha(world), last_name="Phoned in", owner_id=manager)
    db_session.add(lead)
    db_session.flush()
    body = ok(api.get(transcript_url(lead.id), headers=auth("alpha.manager")))
    assert body == {"started_at": None, "messages": []}


# --- the 30-day clean-up in the worker --------------------------------------------------------


def _age(db_session: Session, tenant_id: uuid.UUID, days: int) -> None:
    """Make every conversation of the tenant look ``days`` old."""
    bind_tenant(db_session, tenant_id)
    db_session.execute(
        update(PublicChatSession).values(updated_at=datetime.now(UTC) - timedelta(days=days))
    )


def _conversations(db_session: Session, tenant_id: uuid.UUID) -> list[PublicChatSession]:
    bind_tenant(db_session, tenant_id)
    return list(db_session.scalars(select(PublicChatSession)))


def test_old_conversations_without_a_lead_are_deleted(make_api, world, worker, db_session) -> None:
    api = make_api()
    chat(api, "Hello, just looking", ip="198.51.100.1")  # never left details
    saved_lead(api, db_session, world)  # became a lead: kept with the lead
    _age(db_session, alpha(world), 31)
    chat(api, "Hello again", ip="198.51.100.2")  # new today: kept

    beta_api = make_api(public_chat_tenant_slug="beta-quotes")
    chat(beta_api, "Hello from beta", ip="198.51.100.3")
    _age(db_session, world.users["beta.admin"].tenant_id, 31)

    worker()
    left = _conversations(db_session, alpha(world))
    assert len(left) == 2
    assert sum(1 for c in left if c.lead_id) == 1
    ids = {c.id for c in left}
    messages = db_session.scalars(select(PublicChatMessage)).all()
    assert {m.session_id for m in messages} == ids  # the old messages went too
    # Beta's old conversation is beta's own clean-up, also done (each tenant on its own).
    assert _conversations(db_session, world.users["beta.admin"].tenant_id) == []


def test_conversations_younger_than_the_retention_stay(make_api, world, worker, db_session):
    chat(make_api(), "Hello, just looking")
    _age(db_session, alpha(world), 29)
    worker()
    assert len(_conversations(db_session, alpha(world))) == 1


def test_the_retention_is_a_setting_with_a_floor() -> None:
    assert settings().public_chat_retention_days == 30
    assert settings(public_chat_retention_days=7).public_chat_retention_days == 7
    with pytest.raises(ValueError):
        settings(public_chat_retention_days=0)
