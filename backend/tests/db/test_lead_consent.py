# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""E-mail consent on leads (ADR 0036, FM1): the answer, its date, and where it stops a message.

Leads had no consent answer, so nothing could stop an e-mail to a lead who said no. These tests
play the real API and the real worker.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.modules.contacts.models import Contact
from app.modules.leads import api as leads_api
from app.modules.leads.models import Lead
from tests.db.conftest import setup_lead_context
from tests.db.test_communications_send import (  # noqa: F401 - fixtures used by name
    EMAILS,
    api,
    auth,
    leads,
    mailer,
    ok,
    send,
    worker,
    world,
)

LEADS = "/api/v1/leads"


def patch_lead(
    api: TestClient, auth, lead_id: Any, version: int, user: str = "alpha.agent1", **fields: Any
) -> Any:
    return api.patch(f"{LEADS}/{lead_id}", json={"version": version, **fields}, headers=auth(user))


def read_lead(api: TestClient, auth, lead_id: Any, user: str = "alpha.agent1") -> dict[str, Any]:
    response = api.get(f"{LEADS}/{lead_id}", headers=auth(user))
    assert response.status_code == 200, response.text
    return response.json()


# --- the answer and its date --------------------------------------------------------------------


def test_a_lead_starts_as_unknown_without_a_date(api, auth, world, leads) -> None:
    lead = read_lead(api, auth, leads["L1"])
    assert (lead["email_consent"], lead["email_consent_at"]) == ("unknown", None)


def test_the_server_dates_the_answer_and_clears_the_date_on_reset(api, auth, world, leads) -> None:
    lead = read_lead(api, auth, leads["L1"])
    granted = ok(patch_lead(api, auth, lead["id"], lead["version"], email_consent="granted"))
    assert granted["email_consent"] == "granted"
    assert granted["email_consent_at"] is not None
    reset = ok(patch_lead(api, auth, lead["id"], granted["version"], email_consent="unknown"))
    assert (reset["email_consent"], reset["email_consent_at"]) == ("unknown", None)


def test_a_client_cannot_back_date_the_answer(api, auth, world, leads) -> None:
    lead = read_lead(api, auth, leads["L1"])
    response = patch_lead(
        api,
        auth,
        lead["id"],
        lead["version"],
        email_consent="granted",
        email_consent_at="2020-01-01T00:00:00Z",
    )
    assert response.status_code == 422


@pytest.mark.parametrize("value", [None, "yes", "", "GRANTED"])
def test_impossible_answers_are_refused(api, auth, world, leads, value) -> None:
    lead = read_lead(api, auth, leads["L1"])
    response = patch_lead(api, auth, lead["id"], lead["version"], email_consent=value)
    assert response.status_code == 422


def test_another_agent_or_organisation_cannot_change_it(api, auth, world, leads) -> None:
    lead = read_lead(api, auth, leads["L1"])
    for user in ("alpha.agent2", "beta.admin"):
        response = patch_lead(
            api, auth, lead["id"], lead["version"], user=user, email_consent="withdrawn"
        )
        assert response.status_code == 404
    assert read_lead(api, auth, leads["L1"])["email_consent"] == "unknown"


def test_a_change_is_audited_without_personal_data(api, auth, world, leads, db_session) -> None:
    lead = read_lead(api, auth, leads["L1"])
    patch_lead(api, auth, lead["id"], lead["version"], email_consent="withdrawn")
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == leads["L1"], AuditLog.action == "lead.updated")
    ).first()
    assert entry is not None
    assert entry.changes["email_consent"] == {"old": "unknown", "new": "withdrawn"}
    assert "l1@example.test" not in str(entry.changes)


# --- the database keeps the answer and the date together ----------------------------------------


@pytest.mark.parametrize(
    ("values", "rule"),
    [
        ({"email_consent": "maybe"}, "email_consent_allowed"),
        ({"email_consent": "granted"}, "consent_dated"),  # an answer without a date
    ],
)
def test_the_database_refuses_impossible_rows(world, db_session, values, rule) -> None:
    owner = world.users["alpha.agent1"]
    setup_lead_context(db_session, owner.tenant_id, owner.id)
    with pytest.raises(IntegrityError, match=rule), db_session.begin_nested():
        db_session.add(Lead(tenant_id=owner.tenant_id, owner_id=owner.id, last_name="Db", **values))
        db_session.flush()


# --- it stops a message: when it is queued ------------------------------------------------------


def test_a_withdrawn_lead_cannot_be_e_mailed(api, auth, world, leads) -> None:
    lead = read_lead(api, auth, leads["L1"])
    patch_lead(api, auth, lead["id"], lead["version"], email_consent="withdrawn")
    response = send(api, auth, lead_id=str(leads["L1"]))
    assert (response.status_code, response.json()["code"]) == (409, "consent_withdrawn")


def test_unknown_and_granted_leads_can_still_be_e_mailed(api, auth, world, leads) -> None:
    ok(send(api, auth, lead_id=str(leads["L1"])), 201)  # unknown is fine for a service message
    lead = read_lead(api, auth, leads["L1"])
    patch_lead(api, auth, lead["id"], lead["version"], email_consent="granted")
    ok(send(api, auth, lead_id=str(leads["L1"])), 201)


# --- it stops a message: just before it leaves --------------------------------------------------


def test_consent_withdrawn_after_queueing_stops_the_lead_e_mail(
    api, auth, world, leads, mailer, worker
) -> None:
    message = ok(send(api, auth, lead_id=str(leads["L1"])), 201)
    lead = read_lead(api, auth, leads["L1"])
    patch_lead(api, auth, lead["id"], lead["version"], email_consent="withdrawn")
    worker()
    assert mailer.sent == []
    read = ok(api.get(f"{EMAILS}/{message['id']}", headers=auth("alpha.agent1")))
    assert (read["status"], read["error_code"]) == ("failed", "consent_withdrawn")


def test_the_worker_check_answers_for_a_lead_the_sender_no_longer_owns(
    world, leads, db_session
) -> None:
    """The worker binds only the tenant; the check reads one column as the sender, all scope."""
    tenant = world.users["alpha.agent1"].tenant_id
    bind_tenant(db_session, tenant)
    # agent2 does not own L1, but the check must still see it (and not say "no such lead").
    assert not leads_api.email_consent_withdrawn(
        db_session, tenant, leads["L1"], reader_user_id=world.users["alpha.agent2"].id
    )
    # Nothing stays bound afterwards.
    assert db_session.info.get("user_id") is None
    # A lead that does not exist counts as withdrawn (fail closed), like a missing contact.
    assert leads_api.email_consent_withdrawn(
        db_session, tenant, uuid.uuid4(), reader_user_id=world.users["alpha.agent2"].id
    )


def test_the_worker_check_restores_the_previous_binding(world, leads, db_session) -> None:
    owner = world.users["alpha.agent1"]
    bind_tenant(db_session, owner.tenant_id)
    setup_lead_context(db_session, owner.tenant_id, owner.id)
    leads_api.email_consent_withdrawn(
        db_session, owner.tenant_id, leads["L1"], reader_user_id=world.users["alpha.agent2"].id
    )
    assert db_session.info.get("user_id") == str(owner.id)
    assert db_session.info.get("lead_scope") is not None
