# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Proposal decks of a quote through the real API, worker and PostgreSQL (ADR 0032, PD3).

Uses the people and records of test_quotes_api.py (agent1 owns A1 and writes its quotes; customer
-> A1, customer2 -> A2; tenant beta is separate). Files go to an in-memory store.
"""

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import ForbiddenError
from app.core.mail import MemoryMailer
from app.core.outbox import OutboxJob, enqueue, run_next_job
from app.core.storage import MemoryFileStore
from app.modules.documents import api as documents_api
from app.modules.documents.models import Document
from app.modules.proposal_decks import service as deck_service
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

BRANDING = "/api/v1/branding"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


@pytest.fixture
def run_jobs(db_connection: Connection, files: MemoryFileStore):
    settings = Settings(
        _env_file=None, database_url=UNREACHABLE_DATABASE_URL, oidc_issuer=TEST_ISSUER
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, files, MemoryMailer()))

    def run() -> int:
        count = 0
        while run_next_job(factory, handlers, max_attempts=5) is not None:
            count += 1
        return count

    return run


def approved(api: TestClient, auth: Headers, world: World, **extra: Any) -> Any:
    quote = new_quote(api, auth, world, **extra)
    return ok(step(api, auth, "alpha.agent1", quote, "submit"))


def ask(api: TestClient, auth: Headers, quote: Any, user: str = "alpha.agent1") -> Any:
    return api.post(f"{QUOTES}/{quote['id']}/deck", headers=auth(user))


def state(api: TestClient, auth: Headers, quote: Any, user: str = "alpha.agent1") -> Any:
    return api.get(f"{QUOTES}/{quote['id']}/deck", headers=auth(user))


def decks(db_session: Session, quote: Any) -> list[Document]:
    return list(
        db_session.scalars(
            select(Document)
            .where(Document.record_id == uuid.UUID(quote["id"]), Document.purpose == "quote_deck")
            .order_by(Document.created_at)
        )
    )


def pdf_text(files: MemoryFileStore, doc: Document) -> str:
    return "\n".join(
        page.extract_text() for page in PdfReader(io.BytesIO(files.get(doc.storage_key))).pages
    )


def set_branding(api: TestClient, auth: Headers, version: int = 0, **over: Any) -> Any:
    body = {
        "version": version,
        "primary_color": "0b6e4f",
        "about_text": "We build homes in Vijayawada.",
        "terms_text": "Payment within 30 days.",
        "contact_line": "sales@example.test",
        "footer_line": "Acme Homes",
        **over,
    }
    return ok(api.put(BRANDING, json=body, headers=auth("alpha.admin")))


# --- asking for a deck -----------------------------------------------------------------------


def test_a_draft_quote_has_no_deck(api, auth, world, files) -> None:
    draft = new_quote(api, auth, world)
    assert code_of(ask(api, auth, draft)) == (409, "quote_not_ready_for_deck")
    status = ok(state(api, auth, draft))
    assert status["status"] == "not_available" and "approved" in status["reason"]


def test_an_approved_quote_queues_exactly_one_job_with_ids_only(
    api, auth, world, files, db_session
) -> None:
    quote = approved(api, auth, world)
    response = ask(api, auth, quote)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    [job] = db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck")).all()
    assert set(job.payload) == {"quote_id", "requested_by"}
    assert job.payload["quote_id"] == quote["id"]
    assert job.payload["requested_by"] == str(world.users["alpha.agent1"].id)
    assert job.tenant_id == world.users["alpha.agent1"].tenant_id


def test_asking_again_while_one_is_being_made_is_refused(api, auth, world, files) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    assert code_of(ask(api, auth, quote)) == (409, "deck_pending")
    assert ok(state(api, auth, quote))["status"] == "queued"


def test_an_old_revision_cannot_get_a_deck(api, auth, world, files) -> None:
    sent = to_sent(api, auth, world)
    ok(step(api, auth, "alpha.agent1", sent, "revise"), 201)
    assert code_of(ask(api, auth, sent)) == (409, "quote_superseded")


def test_the_hourly_limit_stops_a_flood(api, auth, world, files, run_jobs) -> None:
    api.app.state.settings = api.app.state.settings.model_copy(
        update={"proposal_decks_per_user_hour": 2}
    )
    quote = approved(api, auth, world)
    for _ in range(2):
        assert ask(api, auth, quote).status_code == 202
        run_jobs()
    assert code_of(ask(api, auth, quote)) == (429, "deck_rate_limited")


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("alpha.agent2", 404),  # same tenant, not their customer
        ("beta.admin", 404),  # other tenant
        ("alpha.support", 403),  # role without quotes
        ("alpha.customer", 403),  # customers use the portal address
    ],
)
def test_who_may_not_ask_for_a_deck(api, auth, world, files, db_session, user, expected) -> None:
    quote = approved(api, auth, world)
    assert ask(api, auth, quote, user).status_code == expected
    assert db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck")).all() == []


def test_a_manager_may_ask_for_any_deck(api, auth, world, files) -> None:
    quote = approved(api, auth, world)
    assert ask(api, auth, quote, "alpha.manager").status_code == 202


def test_a_made_up_quote_is_not_found(api, auth, world, files) -> None:
    ghost = {"id": str(uuid.uuid4())}
    assert ask(api, auth, ghost).status_code == 404
    assert state(api, auth, ghost).status_code == 404


def test_the_request_is_audited(api, auth, world, files, db_session) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    row = db_session.scalars(select(AuditLog).where(AuditLog.action == "deck.requested")).one()
    assert str(row.entity_id) == quote["id"] and row.actor_user_id == world.users["alpha.agent1"].id


# --- the worker -----------------------------------------------------------------------------


def test_the_worker_draws_and_stores_the_deck(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    assert run_jobs() == 1
    [doc] = decks(db_session, quote)
    assert (doc.content_type, doc.customer_visible, doc.record_type) == (
        "application/pdf",
        True,
        "quote",
    )
    assert doc.created_by_user_id == world.users["alpha.agent1"].id
    assert doc.file_name == f"QT-{quote['number']:04d}-proposal.pdf"
    assert files.get(doc.storage_key).startswith(b"%PDF-")
    status = ok(state(api, auth, quote))
    assert status["status"] == "ready" and status["file_name"] == doc.file_name
    assert status["size_bytes"] == doc.size_bytes and status["refresh_failed"] is False


def test_the_deck_shows_the_quote_as_the_customer_sees_it(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world, internal_note="SECRET-INTERNAL-NOTE", customer_note="Hello")
    ask(api, auth, quote)
    run_jobs()
    text = pdf_text(files, decks(db_session, quote)[0])
    assert quote["title"] in text and f"QT-{quote['number']:04d}" in text
    assert "Hello" in text and "SECRET-INTERNAL-NOTE" not in text
    assert "Investment" in text


def test_the_deck_uses_the_organisations_branding(
    api, auth, world, files, run_jobs, db_session
) -> None:
    set_branding(api, auth)
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    text = pdf_text(files, decks(db_session, quote)[0])
    assert "We build homes in Vijayawada." in text and "Payment within 30 days." in text
    assert "sales@example.test" in text and "Acme Homes" in text


def test_the_deck_without_branding_still_works(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    text = pdf_text(files, decks(db_session, quote)[0])
    assert "Next steps" in text and "About " not in text


def test_asking_again_with_nothing_changed_stores_nothing_new(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    ask(api, auth, quote)
    run_jobs()
    assert len(decks(db_session, quote)) == 1 and len(files.objects) == 1
    created = db_session.scalars(select(AuditLog).where(AuditLog.action == "deck.created")).all()
    assert (
        len(created) == 1
    )  # the repeat found the same bytes: nothing was created, nothing audited


def test_a_changed_branding_gives_a_new_deck_and_the_newest_is_served(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    set_branding(api, auth, about_text="A different story.")
    ask(api, auth, quote)
    run_jobs()
    old, new = decks(db_session, quote)
    assert old.sha256 != new.sha256 and "A different story." in pdf_text(files, new)
    link = ok(api.get(f"{QUOTES}/{quote['id']}/deck/link", headers=auth("alpha.agent1")))
    assert new.storage_key.split("/")[-1] in link["url"]


def test_the_deck_creation_is_audited_with_ids_and_sizes_only(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    row = db_session.scalars(select(AuditLog).where(AuditLog.action == "deck.created")).one()
    assert set(row.changes) == {"document_id", "size_bytes", "branding_version"}
    assert str(row.entity_id) == quote["id"]


def forged_job(world: World, db_connection: Connection, payload: dict[str, Any]) -> uuid.UUID:
    tenant = world.users["alpha.agent1"].tenant_id
    factory = session_factory_for(db_connection)
    with factory() as session, session.begin():
        bind_tenant(session, tenant)
        return enqueue(session, tenant_id=tenant, kind="quote.deck", payload=payload).id


def job_status(db_session: Session, world: World, job_id: uuid.UUID) -> tuple[str, str | None]:
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    job = db_session.get(OutboxJob, job_id)
    assert job is not None
    db_session.refresh(job)
    return job.status, job.last_error


@pytest.mark.parametrize(
    "payload",
    [{}, {"quote_id": "not-a-uuid"}, {"quote_id": str(uuid.uuid4())}],
)
def test_a_job_with_a_bad_or_unknown_quote_is_dead_not_retried(
    api, auth, world, files, run_jobs, db_connection, db_session, payload
) -> None:
    job_id = forged_job(world, db_connection, payload)
    run_jobs()
    status, error = job_status(db_session, world, job_id)
    assert status == "dead" and error is not None and error.startswith("PermanentJobError")


def test_a_job_for_a_draft_quote_makes_no_deck(
    api, auth, world, files, run_jobs, db_connection, db_session
) -> None:
    draft = new_quote(api, auth, world)
    job_id = forged_job(world, db_connection, {"quote_id": draft["id"]})
    run_jobs()
    assert job_status(db_session, world, job_id)[0] == "dead"
    assert decks(db_session, draft) == [] and files.objects == {}


def test_a_failed_job_without_a_deck_is_reported_as_failed(
    api, auth, world, files, run_jobs, monkeypatch
) -> None:
    from app.core.outbox import PermanentJobError
    from app.modules.proposal_decks import service

    def broken(*_: Any, **__: Any) -> bytes:
        raise PermanentJobError("drawing failed")

    monkeypatch.setattr(service, "render_deck", broken)
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    assert ok(state(api, auth, quote))["status"] == "failed"
    assert (
        code_of(api.get(f"{QUOTES}/{quote['id']}/deck/link", headers=auth("alpha.agent1")))[0]
        == 404
    )


def test_a_job_with_a_bad_requester_id_is_still_made_by_the_system(
    api, auth, world, files, run_jobs, db_connection, db_session
) -> None:
    quote = approved(api, auth, world)
    forged_job(world, db_connection, {"quote_id": quote["id"], "requested_by": "not-a-uuid"})
    run_jobs()
    [doc] = decks(db_session, quote)
    assert doc.created_by_user_id is None


def test_a_job_cannot_reach_another_organisations_quote(
    api, auth, world, files, run_jobs, db_connection, db_session
) -> None:
    quote = approved(api, auth, world)  # an alpha quote
    beta = world.users["beta.admin"].tenant_id
    factory = session_factory_for(db_connection)
    with factory() as session, session.begin():
        bind_tenant(session, beta)
        enqueue(session, tenant_id=beta, kind="quote.deck", payload={"quote_id": quote["id"]})
    run_jobs()
    assert decks(db_session, quote) == []


# --- downloading ----------------------------------------------------------------------------


def test_staff_get_a_signed_link_to_the_deck(api, auth, world, files, run_jobs) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    link = ok(api.get(f"{QUOTES}/{quote['id']}/deck/link", headers=auth("alpha.agent1")))
    assert link["file_name"].endswith("-proposal.pdf") and link["url"].startswith("memory://")


def test_no_link_before_a_deck_exists(api, auth, world, files) -> None:
    quote = approved(api, auth, world)
    response = api.get(f"{QUOTES}/{quote['id']}/deck/link", headers=auth("alpha.agent1"))
    assert code_of(response) == (404, "deck_not_found")


@pytest.mark.parametrize(
    ("user", "expected"),
    [("alpha.agent2", 404), ("beta.admin", 404), ("alpha.support", 403), ("alpha.customer", 403)],
)
def test_who_may_not_get_a_staff_link(api, auth, world, files, run_jobs, user, expected) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    assert api.get(f"{QUOTES}/{quote['id']}/deck/link", headers=auth(user)).status_code == expected
    assert state(api, auth, quote, user).status_code == expected


# --- the customer portal --------------------------------------------------------------------


def portal(api: TestClient, auth: Headers, quote: Any, user: str, tail: str = "") -> Any:
    return api.get(f"{PORTAL}/{quote['id']}/deck{tail}", headers=auth(user))


def test_a_customer_sees_and_downloads_the_deck_of_a_quote_sent_to_them(
    api, auth, world, files, run_jobs
) -> None:
    quote = to_sent(api, auth, world)
    assert ok(portal(api, auth, quote, "alpha.customer"))["status"] == "none"
    assert code_of(portal(api, auth, quote, "alpha.customer", "/link")) == (404, "deck_not_found")
    ask(api, auth, quote)
    # Work in progress is not shown to a customer.
    assert ok(portal(api, auth, quote, "alpha.customer"))["status"] == "none"
    run_jobs()
    shown = ok(portal(api, auth, quote, "alpha.customer"))
    assert shown["status"] == "ready" and shown["file_name"].endswith("-proposal.pdf")
    link = ok(portal(api, auth, quote, "alpha.customer", "/link"))
    assert link["url"].startswith("memory://")


def test_a_customer_cannot_see_a_deck_of_a_quote_that_was_not_sent(
    api, auth, world, files, run_jobs
) -> None:
    quote = approved(api, auth, world)  # approved, not yet sent
    ask(api, auth, quote)
    run_jobs()
    assert portal(api, auth, quote, "alpha.customer").status_code == 404
    assert portal(api, auth, quote, "alpha.customer", "/link").status_code == 404


def test_another_customer_cannot_see_the_deck(api, auth, world, files, run_jobs) -> None:
    quote = to_sent(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    assert portal(api, auth, quote, "alpha.customer2").status_code == 404
    assert portal(api, auth, quote, "alpha.customer2", "/link").status_code == 404


def test_staff_cannot_use_the_portal_address_and_customers_cannot_ask(
    api, auth, world, files, run_jobs
) -> None:
    quote = to_sent(api, auth, world)
    assert portal(api, auth, quote, "alpha.agent1").status_code == 403
    assert ask(api, auth, quote, "alpha.customer").status_code == 403


def test_a_customer_sees_the_newest_deck(api, auth, world, files, run_jobs, db_session) -> None:
    quote = to_sent(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    set_branding(api, auth, about_text="Fresh words.")
    ask(api, auth, quote)
    run_jobs()
    _, new = decks(db_session, quote)
    link = ok(portal(api, auth, quote, "alpha.customer", "/link"))
    assert new.storage_key.split("/")[-1] in link["url"]


# --- unauthenticated and tenant isolation ---------------------------------------------------


def test_every_endpoint_needs_a_sign_in(api, auth, world, files) -> None:
    quote_id = uuid.uuid4()
    assert api.post(f"{QUOTES}/{quote_id}/deck").status_code == 401
    assert api.get(f"{QUOTES}/{quote_id}/deck").status_code == 401
    assert api.get(f"{QUOTES}/{quote_id}/deck/link").status_code == 401
    assert api.get(f"{PORTAL}/{quote_id}/deck/link").status_code == 401


def test_decks_of_one_organisation_are_invisible_to_another(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    bind_tenant(db_session, world.users["beta.admin"].tenant_id)
    assert db_session.scalars(select(Document)).all() == []


# --- the service refuses on its own, and the rarer states --------------------------------------


def read_only_principal(world: World) -> Principal:
    """A staff member who may READ the quotes of the organisation but not change them."""
    user = world.users["alpha.manager"]
    return Principal(
        subject=user.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.SALES_MANAGER}),
        permissions=frozenset({Permission.QUOTE_READ_ALL}),
        user_id=user.id,
        tenant_id=user.tenant_id,
    )


def test_someone_who_may_only_read_the_quote_cannot_ask_for_a_deck_even_past_the_router(
    api, auth, world, files, db_session
) -> None:
    quote = approved(api, auth, world)
    reader = read_only_principal(world)
    bind_tenant(db_session, world.users["alpha.manager"].tenant_id)
    settings = Settings(
        _env_file=None, database_url=UNREACHABLE_DATABASE_URL, oidc_issuer=TEST_ISSUER
    )
    with pytest.raises(ForbiddenError):
        deck_service.request_deck(db_session, reader, uuid.UUID(quote["id"]), settings)
    assert db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck")).all() == []
    # ...but reading the state is fine.
    assert (
        deck_service.deck_state(db_session, reader, uuid.UUID(quote["id"]), customer=False).state
        == "none"
    )


def test_a_deck_not_marked_for_the_customer_is_never_shown_to_them(
    api, auth, world, files, db_session
) -> None:
    quote = to_sent(api, auth, world)
    tenant = world.users["alpha.agent1"].tenant_id
    bind_tenant(db_session, tenant)
    documents_api.store_generated_document(
        db_session,
        files,
        tenant_id=tenant,
        record_type="quote",
        record_id=uuid.UUID(quote["id"]),
        purpose="quote_deck",
        file_name="internal.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4 internal",
        customer_visible=False,
        created_by_user_id=None,
        unique_by_content=True,
    )
    assert ok(portal(api, auth, quote, "alpha.customer"))["status"] == "none"
    assert code_of(portal(api, auth, quote, "alpha.customer", "/link")) == (404, "deck_not_found")
    # Staff do see it.
    assert ok(state(api, auth, quote))["status"] == "ready"


def test_a_failed_refresh_keeps_the_old_deck_and_says_so(
    api, auth, world, files, run_jobs, monkeypatch
) -> None:
    from app.core.outbox import PermanentJobError

    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()

    def broken(*_: Any, **__: Any) -> bytes:
        raise PermanentJobError("drawing failed")

    monkeypatch.setattr(deck_service, "render_deck", broken)
    ask(api, auth, quote)
    run_jobs()
    status = ok(state(api, auth, quote))
    assert status["status"] == "ready" and status["refresh_failed"] is True
    link = ok(api.get(f"{QUOTES}/{quote['id']}/deck/link", headers=auth("alpha.agent1")))
    assert link["url"].startswith("memory://")  # the earlier deck is still served
