# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Communication Center, step CC4 (ADR 0012): conversation history, the Communication Center
list and logging a received e-mail, through the real API.

People and records from test_quotes_api.py: agent1 owns A1 / C1 / O1, agent2 owns A2 / C2 / O2.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.outbox import OutboxJob
from app.modules.activities.models import Activity
from tests.db.test_communications_send import (  # noqa: F401 - fixtures used by name
    C1_EMAIL,
    EMAILS,
    give_email,
    leads,
    send,
    set_contact,
    to_c1,
)
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    World,
    api,
    auth,
    code_of,
    ok,
    world,
)

HISTORY = "/api/v1/communications/history"
RECEIVED = f"{EMAILS}/received"


def history(api: TestClient, auth, user: str, **record: Any) -> Any:
    return api.get(HISTORY, params=record, headers=auth(user))


def subjects(response: Any) -> list[str]:
    return [m["subject"] for m in ok(response)["items"]]


def listed(api: TestClient, auth, user: str, **params: Any) -> list[str]:
    return [m["subject"] for m in ok(api.get(EMAILS, params=params, headers=auth(user)))["items"]]


def log_received(api: TestClient, auth, user: str = "alpha.agent1", **body: Any) -> Any:
    payload = {"subject": "Re: Your enquiry", "body": "Thanks, call me tomorrow.", **body}
    return api.post(RECEIVED, json=payload, headers=auth(user))


@pytest.fixture
def mails(api: TestClient, auth, world: World, db_session: Session) -> None:
    """Five e-mails, sent through the API one after another (newest last)."""
    give_email(db_session, world, "C1")
    set_contact(db_session, world, "C2", email="c2@example.test")
    ok(send(api, auth, subject="1 plain to C1", **to_c1(world)), 201)
    ok(
        send(api, auth, subject="2 C1 under A1", **to_c1(world, account_id=str(world.ids["A1"]))),
        201,
    )
    ok(
        send(
            api, auth, subject="3 C1 under O1", **to_c1(world, opportunity_id=str(world.ids["O1"]))
        ),
        201,
    )
    ok(send(api, auth, "alpha.manager", subject="4 manager to C1", **to_c1(world)), 201)
    c2 = {"contact_id": str(world.ids["C2"])}
    ok(send(api, auth, "alpha.agent2", subject="5 agent2 to C2", **c2), 201)


# --- history per record -------------------------------------------------------------------------


def test_a_contacts_history_shows_every_e_mail_to_them_newest_first(api, auth, world, mails):
    response = history(api, auth, "alpha.agent1", contact_id=str(world.ids["C1"]))
    assert subjects(response) == [
        "4 manager to C1",  # a colleague's e-mail too: the history follows the record's rules
        "3 C1 under O1",
        "2 C1 under A1",
        "1 plain to C1",
    ]
    assert ok(response)["total"] == 4


def test_an_accounts_history_includes_its_contacts_and_deals(api, auth, world, mails) -> None:
    response = history(api, auth, "alpha.agent1", account_id=str(world.ids["A1"]))
    assert subjects(response) == [
        "4 manager to C1",
        "3 C1 under O1",
        "2 C1 under A1",
        "1 plain to C1",
    ]
    assert subjects(history(api, auth, "alpha.agent2", account_id=str(world.ids["A2"]))) == [
        "5 agent2 to C2"
    ]


def test_a_deals_history_shows_what_was_filed_under_it(api, auth, world, mails) -> None:
    response = history(api, auth, "alpha.agent1", opportunity_id=str(world.ids["O1"]))
    assert subjects(response) == ["3 C1 under O1"]


def test_a_leads_history(api, auth, world, leads) -> None:
    ok(send(api, auth, subject="To the lead", lead_id=str(leads["L1"])), 201)
    assert subjects(history(api, auth, "alpha.agent1", lead_id=str(leads["L1"]))) == ["To the lead"]
    assert subjects(history(api, auth, "alpha.manager", lead_id=str(leads["L1"]))) == [
        "To the lead"
    ]
    assert history(api, auth, "alpha.agent2", lead_id=str(leads["L1"])).status_code == 404


def test_history_is_paged(api, auth, world, mails) -> None:
    page = ok(
        api.get(
            HISTORY,
            params={"contact_id": str(world.ids["C1"]), "limit": 2, "offset": 1},
            headers=auth("alpha.agent1"),
        )
    )
    assert [m["subject"] for m in page["items"]] == ["3 C1 under O1", "2 C1 under A1"]
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 1)


def test_a_support_agent_reads_the_history_of_a_contact_they_can_see(api, auth, world, mails):
    response = history(api, auth, "alpha.support", contact_id=str(world.ids["C1"]))
    assert ok(response)["total"] == 4


@pytest.mark.parametrize(
    "user, record, expected",
    [
        ("alpha.agent2", "C1", 404),  # record-level: not agent2's contact
        ("alpha.agent2", "A1", 404),
        ("alpha.agent2", "O1", 404),
        ("beta.admin", "C1", 404),  # another organisation
        ("alpha.customer", "C1", 403),  # role
    ],
)
def test_who_may_not_read_a_history(api, auth, world, mails, user, record, expected) -> None:
    field = {"C": "contact_id", "A": "account_id", "O": "opportunity_id"}[record[0]]
    assert history(api, auth, user, **{field: str(world.ids[record])}).status_code == expected


def test_a_history_needs_exactly_one_known_record(api, auth, world) -> None:
    assert history(api, auth, "alpha.agent1").status_code == 422
    two = history(
        api, auth, "alpha.agent1", contact_id=str(world.ids["C1"]), account_id=str(world.ids["A1"])
    )
    assert two.status_code == 422
    assert history(api, auth, "alpha.manager", contact_id=str(uuid.uuid4())).status_code == 404


# --- the Communication Center list --------------------------------------------------------------


def test_agents_list_only_what_they_wrote_managers_list_everything(api, auth, world, mails):
    assert listed(api, auth, "alpha.agent1") == ["3 C1 under O1", "2 C1 under A1", "1 plain to C1"]
    assert listed(api, auth, "alpha.agent2") == ["5 agent2 to C2"]
    assert listed(api, auth, "alpha.manager") == [
        "5 agent2 to C2",
        "4 manager to C1",
        "3 C1 under O1",
        "2 C1 under A1",
        "1 plain to C1",
    ]
    assert listed(api, auth, "beta.admin") == []
    assert api.get(EMAILS, headers=auth("alpha.customer")).status_code == 403


def test_the_list_filters_in_the_database(api, auth, world, mails) -> None:
    manager = "alpha.manager"
    assert listed(api, auth, manager, q="under") == ["3 C1 under O1", "2 C1 under A1"]
    assert listed(api, auth, manager, q="%") == []  # a wildcard is matched literally
    assert listed(api, auth, manager, status="sent") == []  # the worker hasn't run
    assert len(listed(api, auth, manager, status="queued")) == 5
    agent2 = str(world.users["alpha.agent2"].id)
    assert listed(api, auth, manager, sent_by_user_id=agent2) == ["5 agent2 to C2"]
    # An agent can't widen the list by naming a colleague: it stays their own e-mails only.
    assert listed(api, auth, "alpha.agent1", sent_by_user_id=agent2) == []
    page = ok(api.get(EMAILS, params={"limit": 2}, headers=auth(manager)))
    assert (len(page["items"]), page["total"]) == (2, 5)
    assert api.get(EMAILS, params={"status": "lost"}, headers=auth(manager)).status_code == 422


# --- logging a received e-mail ------------------------------------------------------------------


def test_logging_a_received_e_mail(api, auth, world, db_session) -> None:
    give_email(db_session, world)
    response = log_received(api, auth, **to_c1(world, account_id=str(world.ids["A1"])))
    logged = ok(response, 201)
    assert response.headers["Location"] == f"{EMAILS}/{logged['id']}"
    assert (logged["direction"], logged["status"]) == ("inbound_logged", "logged")
    assert logged["to_address"] == C1_EMAIL  # the person's address, from the record
    assert logged["sent_at"] is None

    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    # Nothing is sent: no outbox job for a logged e-mail.
    jobs = db_session.scalars(
        select(OutboxJob).where(OutboxJob.payload["message_id"].astext == logged["id"])
    ).all()
    assert jobs == []
    [activity] = db_session.scalars(
        select(Activity).where(Activity.contact_id == world.ids["C1"], Activity.kind == "email")
    ).all()
    assert activity.subject == "E-mail received: Re: Your enquiry"
    [audit] = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(logged["id"]))
    ).all()
    assert audit.action == "email.logged"

    assert subjects(history(api, auth, "alpha.agent1", contact_id=str(world.ids["C1"]))) == [
        "Re: Your enquiry"
    ]
    assert listed(api, auth, "alpha.agent1", direction="inbound_logged") == ["Re: Your enquiry"]


def test_a_received_e_mail_is_logged_even_without_consent(api, auth, world, db_session) -> None:
    give_email(db_session, world)
    set_contact(db_session, world, email_consent="withdrawn", email_consent_at=func.now())
    ok(log_received(api, auth, **to_c1(world)), 201)  # consent is about writing TO them


def test_logged_e_mails_do_not_count_towards_the_sending_limit(api, auth, world, db_session):
    give_email(db_session, world)
    api.app.state.settings = api.app.state.settings.model_copy(
        update={"communication_emails_per_hour": 1}
    )
    ok(log_received(api, auth, **to_c1(world)), 201)
    ok(log_received(api, auth, **to_c1(world)), 201)
    ok(send(api, auth, **to_c1(world)), 201)


@pytest.mark.parametrize(
    "body",
    [
        {"from_address": "someone@example.test"},  # the address comes from the record
        {"status": "sent"},
        {"subject": ""},
        {"body": " "},
    ],
)
def test_invalid_logged_e_mails_are_refused(api, auth, world, db_session, body) -> None:
    give_email(db_session, world)
    assert log_received(api, auth, **to_c1(world), **body).status_code == 422


def test_who_may_not_log_a_received_e_mail(api, auth, world, leads, db_session) -> None:
    give_email(db_session, world)
    assert log_received(api, auth, "alpha.agent2", **to_c1(world)).status_code == 404
    assert log_received(api, auth, "alpha.agent2", lead_id=str(leads["L1"])).status_code == 404
    assert log_received(api, auth, "beta.admin", **to_c1(world)).status_code == 404
    assert log_received(api, auth, "alpha.customer", **to_c1(world)).status_code == 403
    wrong_deal = log_received(api, auth, **to_c1(world, opportunity_id=str(world.ids["O2"])))
    assert wrong_deal.status_code == 404
    set_contact(db_session, world, email=None)
    assert code_of(log_received(api, auth, **to_c1(world))) == (409, "recipient_has_no_email")
