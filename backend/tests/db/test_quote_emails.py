# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""E-mailing quotes with the PDF attached (ADR 0005, step E2b), through the real API.

Uses the people and records of test_quotes_api.py (agent1 owns A1 and contact C1). The worker
runs in the test with an in-memory file store and mailer.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.mail import MailRejectedError, MailUnavailableError, MemoryMailer
from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.contacts.models import Contact
from app.modules.documents.models import Document
from app.modules.quotes.models import QuoteEvent
from app.worker import WorkerServices, job_handlers, run_due_jobs
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    QUOTES,
    Headers,
    World,
    api,
    auth,
    code_of,
    new_quote,
    ok,
    step,
    world,
)

C1_EMAIL = "ada.c1@example.test"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


@pytest.fixture
def mailer() -> MemoryMailer:
    return MemoryMailer()


@pytest.fixture
def worker(db_connection: Connection, files: MemoryFileStore, mailer: MemoryMailer) -> Any:
    settings = Settings(
        _env_file=None,
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        web_app_url="http://localhost:3000",
        worker_max_attempts=3,
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, files, mailer))
    return lambda: run_due_jobs(factory, handlers, settings)


def give_email(db_session: Session, world: World, key: str = "C1", email: str | None = C1_EMAIL):
    # The contacts belong to tenant alpha; change them with the context a request would have.
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    db_session.execute(
        update(Contact).where(Contact.id == world.ids[key]).values(email=email, first_name="Ada")
    )
    db_session.flush()


def approved(api, auth, world, *, contact: str | None = "C1") -> Any:
    extra = {"contact_id": str(world.ids[contact])} if contact else {}
    quote = new_quote(api, auth, world, **extra)
    return ok(step(api, auth, "alpha.agent1", quote, "submit"))


def email(api, auth, quote, user: str = "alpha.agent1", **body: Any) -> Any:
    return api.post(
        f"{QUOTES}/{quote['id']}/email",
        json={"version": quote["version"], **body},
        headers=auth(user),
    )


def history_notes(api, auth, quote) -> list[str | None]:
    events = ok(api.get(f"{QUOTES}/{quote['id']}/history", headers=auth("alpha.agent1")))
    return [e["note"] for e in events]


def jobs_of(db_session: Session, quote: Any) -> list[OutboxJob]:
    return list(
        db_session.scalars(
            select(OutboxJob)
            .where(OutboxJob.payload["quote_id"].astext == quote["id"])
            .order_by(OutboxJob.created_at, OutboxJob.kind)
        )
    )


def test_e_mailing_an_approved_quote_sends_it(api, auth, world, files, db_session) -> None:
    give_email(db_session, world)
    quote = ok(email(api, auth, approved(api, auth, world), message="As discussed on the phone."))
    assert (quote["status"], quote["email_status"]) == ("sent", "sending")
    kinds = sorted(j.kind for j in jobs_of(db_session, quote))
    assert kinds == ["quote.email", "quote.pdf"]
    [job] = [j for j in jobs_of(db_session, quote) if j.kind == "quote.email"]
    assert set(job.payload) == {"quote_id", "event_id"}  # IDs only, no address or text
    assert "As discussed on the phone." in history_notes(api, auth, quote)


def test_the_worker_sends_the_mail_with_the_stored_pdf(
    api, auth, world, files, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    quote = ok(email(api, auth, approved(api, auth, world), message="As discussed."))
    assert worker() == 2  # PDF + e-mail

    [mail] = mailer.sent
    number = f"QT-{quote['number']:04d}"
    assert mail.to == (C1_EMAIL,)
    assert mail.subject == f"Quote {number}: 50 widgets"
    assert mail.reply_to == "alpha.agent1@example.test"  # answers go to the quote's owner
    assert "Hello Ada C1," in mail.text
    assert "As discussed." in mail.text
    assert f"http://localhost:3000/portal/quotes/{quote['id']}" in mail.text
    [attachment] = mail.attachments
    [doc] = db_session.scalars(
        select(Document).where(Document.record_id == uuid.UUID(quote["id"]))
    ).all()
    assert (attachment.filename, attachment.content_type) == (f"{number}.pdf", "application/pdf")
    assert attachment.data == files.get(doc.storage_key)  # exactly the stored PDF

    read = ok(api.get(f"{QUOTES}/{quote['id']}", headers=auth("alpha.agent1")))
    assert read["email_status"] == "sent"
    assert "E-mail sent to Ada C1" in history_notes(api, auth, quote)


def test_the_internal_note_never_goes_into_the_mail(api, auth, world, mailer, worker, db_session):
    give_email(db_session, world)
    quote = new_quote(
        api, auth, world, contact_id=str(world.ids["C1"]), internal_note="Max 20 % - SECRET"
    )
    quote = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    ok(email(api, auth, quote))
    worker()
    assert "SECRET" not in mailer.sent[0].text
    assert "Sent by e-mail" not in mailer.sent[0].text  # default history note is not a message


def test_a_recipient_with_an_address_is_required(api, auth, world, files, db_session) -> None:
    no_contact = approved(api, auth, world, contact=None)
    assert code_of(email(api, auth, no_contact)) == (409, "quote_no_recipient")
    give_email(db_session, world, email=None)
    no_address = approved(api, auth, world)
    assert code_of(email(api, auth, no_address)) == (409, "quote_no_recipient")
    assert jobs_of(db_session, no_contact) == jobs_of(db_session, no_address) == []


def test_only_approved_or_sent_quotes_can_be_e_mailed(api, auth, world, files, db_session) -> None:
    give_email(db_session, world)
    draft = new_quote(api, auth, world, contact_id=str(world.ids["C1"]))
    assert code_of(email(api, auth, draft)) == (409, "quote_state")
    big = new_quote(
        api,
        auth,
        world,
        contact_id=str(world.ids["C1"]),
        lines=[{"product_id": str(world.ids["P1"]), "quantity": "1", "discount_percent": "30"}],
    )
    pending = ok(step(api, auth, "alpha.agent1", big, "submit"))
    assert pending["status"] == "pending_approval"
    assert code_of(email(api, auth, pending)) == (409, "quote_state")


@pytest.mark.parametrize(
    ("user", "expected"),
    [("alpha.agent2", 404), ("beta.admin", 404), ("alpha.support", 403), ("alpha.customer", 403)],
)
def test_who_may_not_e_mail_a_quote(api, auth, world, files, db_session, user, expected) -> None:
    give_email(db_session, world)
    quote = approved(api, auth, world)
    assert email(api, auth, quote, user=user).status_code == expected
    assert jobs_of(db_session, quote) == []


def test_tampered_or_stale_requests_are_refused(api, auth, world, files, db_session) -> None:
    give_email(db_session, world)
    quote = approved(api, auth, world)
    gone = {**quote, "id": str(uuid.uuid4())}
    assert email(api, auth, gone).status_code == 404
    assert code_of(email(api, auth, {**quote, "version": quote["version"] + 5})) == (
        409,
        "version_conflict",
    )
    too_long = email(api, auth, quote, message="x" * 501)
    assert too_long.status_code == 422
    sneaky = email(api, auth, quote, to="victim@example.test")  # no recipient from the client
    assert sneaky.status_code == 422


def test_a_sent_quote_can_be_e_mailed_again_but_not_twice_at_once(
    api, auth, world, files, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    first = ok(email(api, auth, approved(api, auth, world)))
    again = email(api, auth, first)
    assert code_of(again) == (409, "email_pending")  # the first one is still on its way
    worker()
    first = ok(api.get(f"{QUOTES}/{first['id']}", headers=auth("alpha.agent1")))
    second = ok(email(api, auth, first, message="Here it is again."))
    assert (second["status"], second["email_status"]) == ("sent", "sending")
    assert code_of(email(api, auth, first)) == (409, "version_conflict")  # double click
    worker()
    assert [m.to for m in mailer.sent] == [(C1_EMAIL,), (C1_EMAIL,)]
    assert "Here it is again." in mailer.sent[1].text


def test_a_refused_address_is_noted_and_not_retried(
    api, auth, world, files, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    quote = ok(email(api, auth, approved(api, auth, world)))
    mailer.fail_with = MailRejectedError("550 no such user ada.c1@example.test")
    worker()
    read = ok(api.get(f"{QUOTES}/{quote['id']}", headers=auth("alpha.agent1")))
    assert read["email_status"] == "failed"
    notes = history_notes(api, auth, quote)
    assert "E-mail could not be sent: the mail server refused the address" in notes
    assert not any(C1_EMAIL in (n or "") for n in notes)  # no address in the history
    [job] = [j for j in jobs_of(db_session, quote) if j.kind == "quote.email"]
    assert (job.status, job.attempts, job.last_error) == ("dead", 1, "MailRejectedError")
    # After fixing the address, staff can send it again.
    mailer.fail_with = None
    ok(email(api, auth, read))
    worker()
    assert len(mailer.sent) == 1


def test_a_mail_server_that_is_down_is_retried_later(
    api, auth, world, files, mailer, worker, db_session
) -> None:
    give_email(db_session, world)
    quote = ok(email(api, auth, approved(api, auth, world)))
    mailer.fail_with = MailUnavailableError("ConnectionRefusedError")
    worker()
    [job] = [j for j in jobs_of(db_session, quote) if j.kind == "quote.email"]
    db_session.refresh(job)
    assert (job.status, job.attempts) == ("pending", 1)
    read = ok(api.get(f"{QUOTES}/{quote['id']}", headers=auth("alpha.agent1")))
    assert read["email_status"] == "sending"
    assert mailer.sent == []


def test_a_removed_address_stops_the_mail(api, auth, world, files, mailer, worker, db_session):
    give_email(db_session, world)
    quote = ok(email(api, auth, approved(api, auth, world)))
    give_email(db_session, world, email=None)  # changed before the worker ran
    worker()
    assert mailer.sent == []
    assert "E-mail could not be sent: the contact has no e-mail address" in history_notes(
        api, auth, quote
    )


def test_system_history_entries_have_no_author(api, auth, world, files, worker, db_session):
    give_email(db_session, world)
    quote = ok(email(api, auth, approved(api, auth, world)))
    worker()
    last = db_session.scalars(
        select(QuoteEvent)
        .where(QuoteEvent.quote_id == uuid.UUID(quote["id"]))
        .order_by(QuoteEvent.seq.desc())
        .limit(1)
    ).one()
    assert (last.note, last.actor_user_id) == ("E-mail sent to Ada C1", None)
