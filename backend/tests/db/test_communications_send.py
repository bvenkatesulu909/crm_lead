# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Communication Center, step CC2 (ADR 0012): sending one-to-one e-mails through the real API.

Uses the people and records of test_quotes_api.py: agent1 owns account A1 with contact C1 and
deal O1; agent2 owns A2 / C2 / O2. The worker runs in the test with an in-memory mailer.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.mail import MailRejectedError, MailUnavailableError, MemoryMailer
from app.core.outbox import OutboxJob, enqueue
from app.core.storage import MemoryFileStore
from app.modules.activities.models import Activity
from app.modules.communications.models import EmailMessage, EmailTemplate
from app.modules.contacts.models import Contact
from app.modules.leads.models import Lead
from app.modules.notifications.models import Notification
from app.worker import WorkerServices, job_handlers, run_due_jobs
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    World,
    api,
    auth,
    code_of,
    ok,
    world,
)

EMAILS = "/api/v1/communications/emails"
C1_EMAIL = "ada.c1@example.test"


@pytest.fixture
def mailer() -> MemoryMailer:
    return MemoryMailer()


@pytest.fixture
def worker(db_connection: Connection, mailer: MemoryMailer) -> Any:
    settings = Settings(
        _env_file=None,
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        web_app_url="http://localhost:3000",
        worker_max_attempts=3,
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, MemoryFileStore(), mailer))
    return lambda: run_due_jobs(factory, handlers, settings)


@pytest.fixture
def leads(world: World, committed_world: Session) -> dict[str, uuid.UUID]:
    """A lead with an e-mail address for each alpha agent (the quotes world has none)."""
    made = {}
    for key, owner in (("L1", "alpha.agent1"), ("L2", "alpha.agent2")):
        lead = Lead(
            tenant_id=world.users[owner].tenant_id,
            first_name="Lena",
            last_name=key,
            email=f"{key.lower()}@example.test",
            owner_id=world.users[owner].id,
        )
        committed_world.add(lead)
        committed_world.flush()
        made[key] = lead.id
    committed_world.commit()
    return made


def set_contact(db_session: Session, world: World, key: str = "C1", **values: Any) -> None:
    # The contacts belong to tenant alpha; change them with the context a request would have.
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    db_session.execute(update(Contact).where(Contact.id == world.ids[key]).values(**values))
    db_session.flush()


def give_email(db_session: Session, world: World, key: str = "C1") -> None:
    set_contact(db_session, world, key, email=C1_EMAIL, first_name="Ada")


def send(api: TestClient, auth, user: str = "alpha.agent1", **body: Any) -> Any:
    payload = {"subject": "Your enquiry", "body": "Hello Ada,\n\nthank you for calling.", **body}
    return api.post(EMAILS, json=payload, headers=auth(user))


def to_c1(world: World, **extra: Any) -> dict[str, Any]:
    return {"contact_id": str(world.ids["C1"]), **extra}


def jobs_for(db_session: Session, message_id: str) -> list[OutboxJob]:
    return list(
        db_session.scalars(
            select(OutboxJob).where(OutboxJob.payload["message_id"].astext == message_id)
        )
    )


# --- happy path ---------------------------------------------------------------------------------


def test_an_agent_e_mails_their_contact_and_it_is_queued(api, auth, world, db_session) -> None:
    give_email(db_session, world)
    response = send(api, auth, **to_c1(world, account_id=str(world.ids["A1"])))
    message = ok(response, 201)
    assert response.headers["Location"] == f"{EMAILS}/{message['id']}"
    assert message["status"] == "queued"
    assert message["direction"] == "outbound"
    assert message["to_address"] == C1_EMAIL  # taken from the contact, not from the request
    assert message["account_id"] == str(world.ids["A1"])
    assert message["sent_by_user_id"] == str(world.users["alpha.agent1"].id)

    [job] = jobs_for(db_session, message["id"])
    assert job.kind == "communication.email"
    assert set(job.payload) == {"message_id"}  # IDs only: no address, subject or text

    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    [activity] = db_session.scalars(
        select(Activity).where(Activity.contact_id == world.ids["C1"], Activity.kind == "email")
    ).all()
    assert (activity.status, activity.subject) == ("done", "E-mail: Your enquiry")
    assert activity.body is None  # the text stays in the Communication Center only

    [audit] = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(message["id"]))
    ).all()
    assert audit.action == "email.queued"
    assert C1_EMAIL not in str(audit.changes) and "thank you" not in str(audit.changes)


def test_the_worker_sends_it_with_the_sender_as_reply_to(
    api, auth, world, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    message = ok(send(api, auth, **to_c1(world)), 201)
    assert worker() == 1

    [mail] = mailer.sent
    assert mail.to == (C1_EMAIL,)
    assert mail.subject == "Your enquiry"
    assert mail.text == "Hello Ada,\n\nthank you for calling."
    assert mail.reply_to == "alpha.agent1@example.test"  # the customer's answer reaches a person
    read = ok(api.get(f"{EMAILS}/{message['id']}", headers=auth("alpha.agent1")))
    assert read["status"] == "sent"
    assert read["sent_at"] is not None


def test_running_the_job_twice_sends_only_once(
    api, auth, world, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    message = ok(send(api, auth, **to_c1(world)), 201)
    worker()
    # A duplicate job for the same message (e.g. a retry after a crash) must not mail again.
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    enqueue(
        db_session,
        tenant_id=world.users["alpha.admin"].tenant_id,
        kind="communication.email",
        payload={"message_id": message["id"]},
    )
    db_session.flush()
    worker()
    assert len(mailer.sent) == 1


def test_an_agent_e_mails_their_own_lead(api, auth, world, leads, mailer, worker) -> None:
    message = ok(send(api, auth, lead_id=str(leads["L1"])), 201)
    assert (message["lead_id"], message["to_address"]) == (str(leads["L1"]), "l1@example.test")
    worker()
    assert mailer.sent[0].to == ("l1@example.test",)


def test_a_support_agent_may_e_mail_a_contact_they_can_read(api, auth, world, db_session):
    give_email(db_session, world)
    ok(send(api, auth, "alpha.support", **to_c1(world)), 201)


def test_a_known_template_is_recorded(api, auth, world, committed_world, db_session) -> None:
    give_email(db_session, world)
    template = EmailTemplate(
        tenant_id=world.users["alpha.manager"].tenant_id,
        name="First reply",
        subject="Thank you",
        body="Hello {{recipient.first_name}}",
        created_by_user_id=world.users["alpha.manager"].id,
    )
    committed_world.add(template)
    committed_world.commit()
    message = ok(send(api, auth, **to_c1(world, template_id=str(template.id))), 201)
    assert message["template_id"] == str(template.id)


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},  # no recipient
        {"subject": " "},
        {"body": ""},
        {"body": "x" * 50_001},
        {"subject": "x" * 201},
        {"to": "victim@example.test"},  # the address never comes from the client
        {"status": "sent"},  # server-controlled
        {"sent_by_user_id": str(uuid.uuid4())},  # server-controlled
    ],
)
def test_invalid_requests_are_refused(api, auth, world, db_session, body) -> None:
    give_email(db_session, world)
    recipient = {} if body == {} else to_c1(world)
    assert send(api, auth, **recipient, **body).status_code == 422


def test_exactly_one_recipient_and_no_record_for_a_lead(api, auth, world, leads) -> None:
    both = send(api, auth, lead_id=str(leads["L1"]), contact_id=str(world.ids["C1"]))
    assert both.status_code == 422
    filed = send(api, auth, lead_id=str(leads["L1"]), account_id=str(world.ids["A1"]))
    assert filed.status_code == 422
    two_records = send(
        api,
        auth,
        **to_c1(world, account_id=str(world.ids["A1"]), opportunity_id=str(world.ids["O1"])),
    )
    assert two_records.status_code == 422


def test_a_contact_without_an_address_cannot_be_e_mailed(api, auth, world, db_session) -> None:
    set_contact(db_session, world, email=None)
    assert code_of(send(api, auth, **to_c1(world))) == (409, "recipient_has_no_email")


def test_withdrawn_consent_blocks_e_mail_but_unknown_does_not(api, auth, world, db_session):
    give_email(db_session, world)
    ok(send(api, auth, **to_c1(world)), 201)  # consent "unknown" (the default) is fine
    set_contact(db_session, world, email_consent="withdrawn", email_consent_at=func.now())
    assert code_of(send(api, auth, **to_c1(world))) == (409, "consent_withdrawn")


def test_the_related_record_must_belong_to_the_contacts_account(
    api, auth, world, db_session
) -> None:
    give_email(db_session, world)
    # The manager may read A2 and O2, but they are not C1's account / deal.
    wrong_account = send(
        api, auth, "alpha.manager", **to_c1(world, account_id=str(world.ids["A2"]))
    )
    assert code_of(wrong_account) == (422, "related_record_mismatch")
    wrong_deal = send(
        api, auth, "alpha.manager", **to_c1(world, opportunity_id=str(world.ids["O2"]))
    )
    assert code_of(wrong_deal) == (422, "related_record_mismatch")
    right_deal = send(
        api, auth, "alpha.manager", **to_c1(world, opportunity_id=str(world.ids["O1"]))
    )
    ok(right_deal, 201)


# --- role denial, record-level denial, ID tampering ----------------------------------------------


@pytest.mark.parametrize("user", ["alpha.customer", "alpha.customer2"])
def test_customers_may_not_send(api, auth, world, db_session, user) -> None:
    give_email(db_session, world)
    assert send(api, auth, user, **to_c1(world)).status_code == 403


def test_an_agent_cannot_e_mail_another_agents_records(api, auth, world, leads, db_session):
    give_email(db_session, world)
    assert code_of(send(api, auth, "alpha.agent2", **to_c1(world))) == (
        404,
        "recipient_not_found",
    )
    assert send(api, auth, "alpha.agent2", lead_id=str(leads["L1"])).status_code == 404
    # agent1's own contact, filed under agent2's deal or account: the record is not visible.
    assert send(api, auth, **to_c1(world, opportunity_id=str(world.ids["O2"]))).status_code == 404
    assert send(api, auth, **to_c1(world, account_id=str(world.ids["A2"]))).status_code == 404


def test_tampered_ids_are_not_found(api, auth, world, db_session) -> None:
    give_email(db_session, world)
    assert send(api, auth, contact_id=str(uuid.uuid4())).status_code == 404
    assert send(api, auth, lead_id=str(uuid.uuid4())).status_code == 404
    # Another organisation's admin can't reach alpha's contact.
    assert send(api, auth, "beta.admin", **to_c1(world)).status_code == 404
    unknown_template = send(api, auth, **to_c1(world, template_id=str(uuid.uuid4())))
    assert code_of(unknown_template) == (404, "template_not_found")
    assert db_session.scalars(select(EmailMessage)).all() == []


def test_who_may_read_a_message(api, auth, world, db_session) -> None:
    give_email(db_session, world)
    message = ok(send(api, auth, **to_c1(world)), 201)
    url = f"{EMAILS}/{message['id']}"
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 200  # the sender
    assert api.get(url, headers=auth("alpha.manager")).status_code == 200  # read:all
    for user in ("alpha.agent2", "alpha.support", "beta.admin"):
        assert api.get(url, headers=auth(user)).status_code == 404
    assert api.get(url, headers=auth("alpha.customer")).status_code == 403
    assert api.get(f"{EMAILS}/{uuid.uuid4()}", headers=auth("alpha.manager")).status_code == 404


# --- limits and failures ------------------------------------------------------------------------


def test_the_hourly_sending_limit(api, auth, world, db_session) -> None:
    give_email(db_session, world)
    settings = api.app.state.settings
    api.app.state.settings = settings.model_copy(update={"communication_emails_per_hour": 2})
    ok(send(api, auth, **to_c1(world)), 201)
    ok(send(api, auth, **to_c1(world)), 201)
    assert code_of(send(api, auth, **to_c1(world))) == (429, "send_limit_reached")
    # The limit is per person: a colleague can still write.
    ok(send(api, auth, "alpha.manager", **to_c1(world)), 201)


def test_a_mail_server_that_is_down_is_retried_later(
    api, auth, world, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    message = ok(send(api, auth, **to_c1(world)), 201)
    mailer.fail_with = MailUnavailableError("ConnectionRefusedError")
    worker()
    [job] = jobs_for(db_session, message["id"])
    db_session.refresh(job)
    assert (job.status, job.attempts) == ("pending", 1)
    assert ok(api.get(f"{EMAILS}/{message['id']}", headers=auth("alpha.agent1")))["status"] == (
        "queued"
    )
    assert mailer.sent == []


def test_a_refused_address_fails_and_tells_the_sender(
    api, auth, world, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    message = ok(send(api, auth, **to_c1(world)), 201)
    mailer.fail_with = MailRejectedError(f"550 no such user {C1_EMAIL}")
    worker()  # runs the e-mail job, then the "email_failed" event it published

    read = ok(api.get(f"{EMAILS}/{message['id']}", headers=auth("alpha.agent1")))
    assert (read["status"], read["error_code"]) == ("failed", "recipient_refused")
    [job] = jobs_for(db_session, message["id"])
    assert (job.status, job.attempts) == ("dead", 1)

    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    [event] = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "event.communication.email_failed")
    ).all()
    assert set(event.payload["data"]) == {"message_id", "sender_id"}  # IDs only
    [note] = db_session.scalars(
        select(Notification).where(Notification.user_id == world.users["alpha.agent1"].id)
    ).all()
    assert note.type == "communication.email_failed"
    assert note.title == "E-mail not delivered: Your enquiry"
    assert note.link == f"/contacts/{world.ids['C1']}"
    assert C1_EMAIL not in note.title


def test_consent_withdrawn_before_sending_stops_the_e_mail(
    api, auth, world, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    message = ok(send(api, auth, **to_c1(world)), 201)
    set_contact(db_session, world, email_consent="withdrawn", email_consent_at=func.now())
    worker()
    assert mailer.sent == []
    read = ok(api.get(f"{EMAILS}/{message['id']}", headers=auth("alpha.agent1")))
    assert (read["status"], read["error_code"]) == ("failed", "consent_withdrawn")
