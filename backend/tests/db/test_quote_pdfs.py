# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Stored quote PDFs (ADR 0005, step E2a) through the real API and PostgreSQL.

Uses the people and records of test_quotes_api.py (agent1 owns A1; customer -> A1,
customer2 -> A2; tenant beta is separate). Files go to an in-memory store.
"""

import hashlib
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.mail import MemoryMailer
from app.core.outbox import OutboxJob, enqueue, run_next_job
from app.core.storage import MemoryFileStore
from app.modules.documents.models import Document
from app.worker import WorkerServices, job_handlers
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    PORTAL,
    QUOTES,
    Headers,
    World,
    api,
    auth,
    code_of,
    new_quote,
    ok,
    step,
    to_sent,
    world,
)


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


def pdf(api: TestClient, auth: Headers, user: str, quote: Any, base: str = QUOTES) -> Any:
    return api.get(f"{base}/{quote['id']}/pdf", headers=auth(user))


def documents(db_session: Session, quote_id: str) -> list[Document]:
    return list(
        db_session.scalars(select(Document).where(Document.record_id == uuid.UUID(quote_id)))
    )


def test_sending_queues_exactly_one_pdf_job(api, auth, world, files, db_session) -> None:
    quote = to_sent(api, auth, world)
    jobs = db_session.scalars(
        select(OutboxJob).where(OutboxJob.payload["quote_id"].astext == quote["id"])
    ).all()
    assert [(j.kind, j.status, j.tenant_id) for j in jobs] == [
        ("quote.pdf", "pending", world.users["alpha.agent1"].tenant_id)
    ]


def test_staff_download_the_pdf_of_a_sent_quote(api, auth, world, files, db_session) -> None:
    quote = to_sent(api, auth, world)
    response = pdf(api, auth, "alpha.agent1", quote)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    number = f"QT-{quote['number']:04d}"
    assert response.headers["content-disposition"] == f'attachment; filename="{number}.pdf"'
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content.startswith(b"%PDF-")

    [doc] = documents(db_session, quote["id"])
    assert (doc.purpose, doc.customer_visible, doc.size_bytes) == (
        "quote_pdf",
        True,
        len(response.content),
    )
    assert doc.sha256 == hashlib.sha256(response.content).hexdigest()
    assert doc.created_by_user_id == world.users["alpha.agent1"].id
    tenant = world.users["alpha.agent1"].tenant_id
    assert doc.storage_key == f"tenant/{tenant}/quotes/{quote['id']}/{doc.id}"
    assert list(files.objects) == [doc.storage_key]

    # Downloading again serves the same stored file; nothing new is created.
    again = pdf(api, auth, "alpha.manager", quote)
    assert again.content == response.content
    assert len(documents(db_session, quote["id"])) == 1
    assert len(files.objects) == 1


def test_no_pdf_before_the_quote_is_sent(api, auth, world, files) -> None:
    draft = new_quote(api, auth, world)
    assert code_of(pdf(api, auth, "alpha.agent1", draft)) == (409, "quote_not_sent")
    approved = ok(step(api, auth, "alpha.agent1", draft, "submit"))
    assert code_of(pdf(api, auth, "alpha.agent1", approved)) == (409, "quote_not_sent")
    assert files.objects == {}


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("alpha.agent2", 404),  # same tenant, not their customer
        ("beta.admin", 404),  # other tenant
        ("alpha.support", 403),  # role without quotes
        ("alpha.customer", 403),  # customers use the portal address
    ],
)
def test_who_may_not_download_staff_pdfs(api, auth, world, files, user, expected) -> None:
    quote = to_sent(api, auth, world)
    assert pdf(api, auth, user, quote).status_code == expected
    assert files.objects == {}  # nothing generated for refused callers


def test_unknown_or_tampered_ids_answer_404(api, auth, world, files) -> None:
    assert api.get(f"{QUOTES}/{uuid.uuid4()}/pdf", headers=auth("alpha.admin")).status_code == 404
    assert api.get(f"{QUOTES}/not-a-uuid/pdf", headers=auth("alpha.admin")).status_code == 422


def test_customers_download_their_own_quotes_in_the_portal(api, auth, world, files) -> None:
    quote = to_sent(api, auth, world)
    own = pdf(api, auth, "alpha.customer", quote, PORTAL)
    assert own.status_code == 200 and own.content.startswith(b"%PDF-")
    assert pdf(api, auth, "alpha.customer2", quote, PORTAL).status_code == 404
    assert pdf(api, auth, "alpha.agent1", quote, PORTAL).status_code == 403
    draft = new_quote(api, auth, world)
    assert pdf(api, auth, "alpha.customer", draft, PORTAL).status_code == 404


def test_without_a_file_store_the_download_answers_503(api, auth, world) -> None:
    quote = to_sent(api, auth, world)  # sending still works: the PDF is made later
    assert code_of(pdf(api, auth, "alpha.agent1", quote)) == (503, "files_unavailable")


def test_a_damaged_stored_file_is_refused(api, auth, world, files, db_session) -> None:
    quote = to_sent(api, auth, world)
    ok_response = pdf(api, auth, "alpha.agent1", quote)
    assert ok_response.status_code == 200
    [doc] = documents(db_session, quote["id"])
    files.objects[doc.storage_key] = (b"%PDF- something else", "application/pdf")
    assert code_of(pdf(api, auth, "alpha.agent1", quote)) == (500, "document_integrity")


def worker_services(store: MemoryFileStore) -> WorkerServices:
    settings = Settings(
        _env_file=None, database_url=UNREACHABLE_DATABASE_URL, oidc_issuer=TEST_ISSUER
    )
    return WorkerServices(settings, store, MemoryMailer())


def test_the_worker_stores_the_pdf_of_a_sent_quote(
    api, auth, world, files, db_connection: Connection, db_session
) -> None:
    quote = to_sent(api, auth, world)
    factory = session_factory_for(db_connection)
    handlers = job_handlers(worker_services(files))
    job = run_next_job(factory, handlers, max_attempts=5)
    assert job is not None and job.kind == "quote.pdf"
    [doc] = documents(db_session, quote["id"])
    assert doc.created_by_user_id is None  # made by the system
    status = db_session.scalar(select(OutboxJob.status).where(OutboxJob.id == job.id))
    assert status == "done"
    # The download now serves the worker's file.
    assert hashlib.sha256(pdf(api, auth, "alpha.agent1", quote).content).hexdigest() == doc.sha256
    assert len(files.objects) == 1


def test_a_pdf_job_for_a_missing_quote_is_dead_not_retried(
    world, files, db_connection: Connection, db_session
) -> None:
    factory = session_factory_for(db_connection)
    tenant = world.users["alpha.agent1"].tenant_id
    with factory() as session, session.begin():
        job_id = enqueue(
            session, tenant_id=tenant, kind="quote.pdf", payload={"quote_id": str(uuid.uuid4())}
        ).id
    run_next_job(factory, job_handlers(worker_services(files)), max_attempts=5)
    job = db_session.get(OutboxJob, job_id)
    assert job is not None
    db_session.refresh(job)
    assert (job.status, job.last_error) == ("dead", "PermanentJobError: quote not found")


def test_a_revision_gets_its_own_pdf(api, auth, world, files, db_session) -> None:
    first = to_sent(api, auth, world)
    assert pdf(api, auth, "alpha.agent1", first).status_code == 200
    second = ok(step(api, auth, "alpha.agent1", first, "revise"), 201)
    second = ok(step(api, auth, "alpha.agent1", second, "submit"))
    second = ok(step(api, auth, "alpha.agent1", second, "send"))
    response = pdf(api, auth, "alpha.agent1", second)
    number = f"QT-{second['number']:04d}"
    assert response.headers["content-disposition"] == f'attachment; filename="{number}-rev2.pdf"'
    # The first revision keeps its own PDF (it is what the customer received back then).
    assert len(documents(db_session, first["id"])) == 1
    assert len(documents(db_session, second["id"])) == 1
    assert len(files.objects) == 2
