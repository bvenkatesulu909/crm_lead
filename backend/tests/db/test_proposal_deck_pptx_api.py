# ruff: noqa: F811 - pytest fixtures imported from the other deck tests are used as parameters
"""The PowerPoint version of a proposal deck through the real API, worker and PostgreSQL (ADR 0032
Amendment A, PD6b). The people and records are those of test_quotes_api.py; files go to an in-memory
store. The PDF behaviour itself is covered by test_proposal_deck_api.py: here we check that the
second format is a separate deck (its own job, purpose, state and link) that never replaces the PDF,
and that the same rules apply to it."""

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.outbox import OutboxJob, enqueue
from app.core.storage import MemoryFileStore
from app.modules.documents import api as documents_api
from app.modules.documents.models import Document
from tests.db.conftest import session_factory_for
from tests.db.test_proposal_deck_api import (  # noqa: F401 - fixtures used by name
    approved,
    files,
    run_jobs,
    set_branding,
)
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

PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def ask(api: TestClient, auth: Headers, quote: Any, fmt: str = "pptx", user: str = "alpha.agent1"):
    return api.post(f"{QUOTES}/{quote['id']}/deck?format={fmt}", headers=auth(user))


def state(
    api: TestClient, auth: Headers, quote: Any, fmt: str = "pptx", user: str = "alpha.agent1"
):
    return api.get(f"{QUOTES}/{quote['id']}/deck?format={fmt}", headers=auth(user))


def link(api: TestClient, auth: Headers, quote: Any, fmt: str = "pptx", user: str = "alpha.agent1"):
    return api.get(f"{QUOTES}/{quote['id']}/deck/link?format={fmt}", headers=auth(user))


def portal(api: TestClient, auth: Headers, quote: Any, user: str, tail: str = "", fmt="pptx"):
    return api.get(f"{PORTAL}/{quote['id']}/deck{tail}?format={fmt}", headers=auth(user))


def docs(db_session: Session, quote: Any, purpose: str) -> list[Document]:
    return list(
        db_session.scalars(
            select(Document)
            .where(Document.record_id == uuid.UUID(quote["id"]), Document.purpose == purpose)
            .order_by(Document.created_at)
        )
    )


def slide_text(files: MemoryFileStore, doc: Document) -> str:
    prs = Presentation(io.BytesIO(files.get(doc.storage_key)))
    parts: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if shape.has_table:
                parts.extend(c.text for row in shape.table.rows for c in row.cells)
    return "\n".join(parts)


# --- asking ----------------------------------------------------------------------------------


def test_asking_for_a_powerpoint_queues_its_own_job_with_ids_only(
    api, auth, world, files, db_session
) -> None:
    quote = approved(api, auth, world)
    response = ask(api, auth, quote)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    [job] = db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck_pptx")).all()
    assert set(job.payload) == {"quote_id", "requested_by"}
    assert job.payload["quote_id"] == quote["id"]
    assert db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck")).all() == []


def test_without_a_format_the_pdf_is_still_what_is_asked_for(
    api, auth, world, files, db_session
) -> None:
    quote = approved(api, auth, world)
    assert api.post(f"{QUOTES}/{quote['id']}/deck", headers=auth("alpha.agent1")).status_code == 202
    assert (
        len(db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck")).all()) == 1
    )


@pytest.mark.parametrize("fmt", ["docx", "PPTX", "", "pdf,pptx", "../x"])
def test_an_unknown_format_is_refused_before_anything_happens(
    api, auth, world, files, db_session, fmt
) -> None:
    quote = approved(api, auth, world)
    assert ask(api, auth, quote, fmt).status_code == 422
    assert state(api, auth, quote, fmt).status_code == 422
    assert link(api, auth, quote, fmt).status_code == 422
    assert (
        db_session.scalars(select(OutboxJob).where(OutboxJob.kind.like("quote.deck%"))).all() == []
    )


def test_one_format_being_made_does_not_block_the_other(api, auth, world, files) -> None:
    quote = approved(api, auth, world)
    assert ask(api, auth, quote, "pdf").status_code == 202
    assert ask(api, auth, quote, "pptx").status_code == 202
    assert code_of(ask(api, auth, quote, "pptx")) == (409, "deck_pending")
    assert code_of(ask(api, auth, quote, "pdf")) == (409, "deck_pending")
    assert ok(state(api, auth, quote, "pptx"))["status"] == "queued"
    assert ok(state(api, auth, quote, "pdf"))["status"] == "queued"


def test_a_draft_and_an_old_revision_get_no_powerpoint(api, auth, world, files) -> None:
    draft = new_quote(api, auth, world)
    assert code_of(ask(api, auth, draft)) == (409, "quote_not_ready_for_deck")
    assert ok(state(api, auth, draft))["status"] == "not_available"
    sent = to_sent(api, auth, world)
    ok(step(api, auth, "alpha.agent1", sent, "revise"), 201)
    assert code_of(ask(api, auth, sent)) == (409, "quote_superseded")


def test_the_hourly_limit_counts_both_formats_together(api, auth, world, files, run_jobs) -> None:
    api.app.state.settings = api.app.state.settings.model_copy(
        update={"proposal_decks_per_user_hour": 2}
    )
    quote = approved(api, auth, world)
    assert ask(api, auth, quote, "pdf").status_code == 202
    run_jobs()
    assert ask(api, auth, quote, "pptx").status_code == 202
    run_jobs()
    assert code_of(ask(api, auth, quote, "pptx")) == (429, "deck_rate_limited")
    assert code_of(ask(api, auth, quote, "pdf")) == (429, "deck_rate_limited")


@pytest.mark.parametrize(
    ("user", "expected"),
    [("alpha.agent2", 404), ("beta.admin", 404), ("alpha.support", 403), ("alpha.customer", 403)],
)
def test_who_may_not_ask_for_a_powerpoint(
    api, auth, world, files, db_session, user, expected
) -> None:
    quote = approved(api, auth, world)
    assert ask(api, auth, quote, "pptx", user).status_code == expected
    assert (
        db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "quote.deck_pptx")).all() == []
    )


def test_a_manager_may_ask_for_any_powerpoint(api, auth, world, files) -> None:
    assert ask(api, auth, approved(api, auth, world), "pptx", "alpha.manager").status_code == 202


def test_the_request_is_audited_with_its_format(api, auth, world, files, db_session) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote, "pptx")
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    row = db_session.scalars(select(AuditLog).where(AuditLog.action == "deck.requested")).one()
    assert row.changes == {"format": "pptx"} and str(row.entity_id) == quote["id"]


# --- the worker ------------------------------------------------------------------------------


def test_the_worker_stores_a_powerpoint_with_its_own_purpose(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    assert run_jobs() == 1
    [doc] = docs(db_session, quote, "quote_deck_pptx")
    assert (doc.content_type, doc.customer_visible, doc.record_type) == (PPTX_TYPE, True, "quote")
    assert doc.created_by_user_id == world.users["alpha.agent1"].id
    assert doc.file_name == f"QT-{quote['number']:04d}-proposal.pptx"
    assert files.get(doc.storage_key)[:2] == b"PK"
    assert docs(db_session, quote, "quote_deck") == []
    shown = ok(state(api, auth, quote))
    assert shown["status"] == "ready" and shown["file_name"] == doc.file_name
    assert shown["size_bytes"] == doc.size_bytes and shown["refresh_failed"] is False


def test_the_powerpoint_shows_the_quote_as_the_customer_sees_it(
    api, auth, world, files, run_jobs, db_session
) -> None:
    set_branding(api, auth)
    quote = approved(api, auth, world, internal_note="SECRET-INTERNAL-NOTE", customer_note="Hello")
    ask(api, auth, quote)
    run_jobs()
    text = slide_text(files, docs(db_session, quote, "quote_deck_pptx")[0])
    assert quote["title"] in text and f"QT-{quote['number']:04d}" in text
    assert "Hello" in text and "SECRET-INTERNAL-NOTE" not in text
    assert "Investment" in text and "We build homes in Vijayawada." in text


def test_a_powerpoint_never_replaces_the_pdf(api, auth, world, files, run_jobs, db_session) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote, "pdf")
    run_jobs()
    [pdf] = docs(db_session, quote, "quote_deck")
    ask(api, auth, quote, "pptx")
    run_jobs()
    [pdf_again] = docs(db_session, quote, "quote_deck")
    [pptx] = docs(db_session, quote, "quote_deck_pptx")
    assert pdf_again.id == pdf.id and pptx.id != pdf.id
    assert ok(state(api, auth, quote, "pdf"))["file_name"].endswith(".pdf")
    assert ok(state(api, auth, quote, "pptx"))["file_name"].endswith(".pptx")
    pdf_link = ok(link(api, auth, quote, "pdf"))
    pptx_link = ok(link(api, auth, quote, "pptx"))
    assert pdf.storage_key.split("/")[-1] in pdf_link["url"]
    assert pptx.storage_key.split("/")[-1] in pptx_link["url"]
    assert pdf_link["file_name"].endswith(".pdf") and pptx_link["file_name"].endswith(".pptx")


def test_a_ready_pdf_does_not_make_the_powerpoint_ready(api, auth, world, files, run_jobs) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote, "pdf")
    run_jobs()
    assert ok(state(api, auth, quote, "pdf"))["status"] == "ready"
    assert ok(state(api, auth, quote, "pptx"))["status"] == "none"
    assert code_of(link(api, auth, quote, "pptx")) == (404, "deck_not_found")


def test_asking_again_with_nothing_changed_stores_nothing_new(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    ask(api, auth, quote)
    run_jobs()
    assert len(docs(db_session, quote, "quote_deck_pptx")) == 1 and len(files.objects) == 1
    created = db_session.scalars(select(AuditLog).where(AuditLog.action == "deck.created")).all()
    assert len(created) == 1


def test_a_changed_branding_gives_a_new_powerpoint_and_the_newest_is_served(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    set_branding(api, auth, about_text="A different story.")
    ask(api, auth, quote)
    run_jobs()
    old, new = docs(db_session, quote, "quote_deck_pptx")
    assert old.sha256 != new.sha256 and "A different story." in slide_text(files, new)
    assert new.storage_key.split("/")[-1] in ok(link(api, auth, quote))["url"]


def test_the_creation_is_audited_with_the_format_and_ids_only(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    row = db_session.scalars(select(AuditLog).where(AuditLog.action == "deck.created")).one()
    assert set(row.changes) == {"document_id", "size_bytes", "branding_version", "format"}
    assert row.changes["format"] == "pptx" and str(row.entity_id) == quote["id"]


def test_a_failed_powerpoint_job_is_reported_for_that_format_only(
    api, auth, world, files, run_jobs, db_connection, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote, "pdf")
    run_jobs()
    tenant = world.users["alpha.agent1"].tenant_id
    with session_factory_for(db_connection)() as session, session.begin():
        bind_tenant(session, tenant)
        enqueue(
            session,
            tenant_id=tenant,
            kind="quote.deck_pptx",
            payload={"quote_id": str(uuid.uuid4())},
        )
    run_jobs()
    assert ok(state(api, auth, quote, "pdf"))["status"] == "ready"
    assert ok(state(api, auth, quote, "pdf"))["refresh_failed"] is False


@pytest.mark.parametrize(
    "payload", [{}, {"quote_id": "not-a-uuid"}, {"quote_id": str(uuid.uuid4())}]
)
def test_a_powerpoint_job_with_a_bad_or_unknown_quote_is_dead_not_retried(
    api, auth, world, files, run_jobs, db_connection, db_session, payload
) -> None:
    tenant = world.users["alpha.agent1"].tenant_id
    with session_factory_for(db_connection)() as session, session.begin():
        bind_tenant(session, tenant)
        job_id = enqueue(session, tenant_id=tenant, kind="quote.deck_pptx", payload=payload).id
    run_jobs()
    bind_tenant(db_session, tenant)
    job = db_session.get(OutboxJob, job_id)
    assert job is not None
    db_session.refresh(job)
    assert job.status == "dead" and (job.last_error or "").startswith("PermanentJobError")
    assert (
        db_session.scalars(select(Document).where(Document.purpose == "quote_deck_pptx")).all()
        == []
    )


def test_a_job_for_another_organisations_quote_makes_nothing(
    api, auth, world, files, run_jobs, db_connection, db_session
) -> None:
    quote = approved(api, auth, world)
    beta = world.users["beta.admin"].tenant_id
    with session_factory_for(db_connection)() as session, session.begin():
        bind_tenant(session, beta)
        enqueue(session, tenant_id=beta, kind="quote.deck_pptx", payload={"quote_id": quote["id"]})
    run_jobs()
    assert (
        db_session.scalars(select(Document).where(Document.purpose == "quote_deck_pptx")).all()
        == []
    )


# --- links and the portal --------------------------------------------------------------------


def test_who_may_not_get_a_staff_powerpoint_link(api, auth, world, files, run_jobs) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote)
    run_jobs()
    for user, expected in (
        ("alpha.agent2", 404),
        ("beta.admin", 404),
        ("alpha.support", 403),
        ("alpha.customer", 403),
    ):
        assert link(api, auth, quote, "pptx", user).status_code == expected, user
        assert state(api, auth, quote, "pptx", user).status_code == expected, user


def test_a_customer_gets_the_powerpoint_of_a_quote_sent_to_them(
    api, auth, world, files, run_jobs
) -> None:
    quote = to_sent(api, auth, world)
    assert ok(portal(api, auth, quote, "alpha.customer"))["status"] == "none"
    ask(api, auth, quote)
    assert ok(portal(api, auth, quote, "alpha.customer"))["status"] == "none"  # work in progress
    run_jobs()
    shown = ok(portal(api, auth, quote, "alpha.customer"))
    assert shown["status"] == "ready" and shown["file_name"].endswith("-proposal.pptx")
    assert ok(portal(api, auth, quote, "alpha.customer", "/link"))["url"].startswith("memory://")
    # The PDF was never asked for, so the customer has none.
    assert ok(portal(api, auth, quote, "alpha.customer", fmt="pdf"))["status"] == "none"


def test_a_customer_cannot_reach_a_powerpoint_of_an_unsent_quote_or_of_someone_else(
    api, auth, world, files, run_jobs
) -> None:
    unsent = approved(api, auth, world)
    ask(api, auth, unsent)
    run_jobs()
    assert portal(api, auth, unsent, "alpha.customer").status_code == 404
    assert portal(api, auth, unsent, "alpha.customer", "/link").status_code == 404
    sent = to_sent(api, auth, world)
    ask(api, auth, sent)
    run_jobs()
    assert portal(api, auth, sent, "alpha.customer2").status_code == 404
    assert portal(api, auth, sent, "alpha.customer2", "/link").status_code == 404
    assert portal(api, auth, sent, "alpha.agent1").status_code == 403


def test_a_powerpoint_not_marked_for_the_customer_is_never_shown_to_them(
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
        purpose="quote_deck_pptx",
        file_name="internal.pptx",
        content_type=PPTX_TYPE,
        data=b"PK internal",
        customer_visible=False,
        created_by_user_id=None,
        unique_by_content=True,
    )
    assert ok(portal(api, auth, quote, "alpha.customer"))["status"] == "none"
    assert code_of(portal(api, auth, quote, "alpha.customer", "/link")) == (404, "deck_not_found")
    assert ok(state(api, auth, quote))["status"] == "ready"  # staff do see it


def test_every_endpoint_needs_a_sign_in(api, auth, world, files) -> None:
    quote_id = uuid.uuid4()
    assert api.post(f"{QUOTES}/{quote_id}/deck?format=pptx").status_code == 401
    assert api.get(f"{QUOTES}/{quote_id}/deck?format=pptx").status_code == 401
    assert api.get(f"{QUOTES}/{quote_id}/deck/link?format=pptx").status_code == 401
    assert api.get(f"{PORTAL}/{quote_id}/deck?format=pptx").status_code == 401
    assert api.get(f"{PORTAL}/{quote_id}/deck/link?format=pptx").status_code == 401


# --- the documents module --------------------------------------------------------------------


def test_the_same_bytes_are_stored_once_per_purpose_and_the_database_agrees(
    api, auth, world, files, db_session
) -> None:
    quote = approved(api, auth, world)
    tenant = world.users["alpha.agent1"].tenant_id
    bind_tenant(db_session, tenant)

    def store(purpose: str, data: bytes) -> documents_api.DocumentInfo:
        return documents_api.store_generated_document(
            db_session,
            files,
            tenant_id=tenant,
            record_type="quote",
            record_id=uuid.UUID(quote["id"]),
            purpose=purpose,
            file_name="x.pptx",
            content_type=PPTX_TYPE,
            data=data,
            customer_visible=True,
            created_by_user_id=None,
            unique_by_content=True,
        )

    first = store("quote_deck_pptx", b"PK-one")
    assert store("quote_deck_pptx", b"PK-one").id == first.id
    assert store("quote_deck_pptx", b"PK-two").id != first.id
    assert len(files.objects) == 2
    assert len(docs(db_session, quote, "quote_deck_pptx")) == 2
    with pytest.raises(ValueError):
        store("attachment", b"x")  # only the deck purposes may be stored by content


def _raw_document(tenant: uuid.UUID, record: uuid.UUID, purpose: str, sha: str) -> dict[str, Any]:
    document_id = uuid.uuid4()
    return {
        "id": document_id,
        "tenant_id": tenant,
        "record_type": "quote",
        "record_id": record,
        "purpose": purpose,
        "file_name": "x",
        "content_type": PPTX_TYPE,
        "size_bytes": 1,
        "sha256": sha,
        "storage_key": f"raw/{document_id}",
        "customer_visible": True,
        "group_id": document_id,
        "version_no": 1,
    }


def test_the_database_itself_refuses_a_second_copy_and_an_unknown_purpose(
    api, auth, world, files, db_session
) -> None:
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    quote = approved(api, auth, world)
    tenant, record = world.users["alpha.agent1"].tenant_id, uuid.UUID(quote["id"])
    bind_tenant(db_session, tenant)
    sha = "a" * 64
    db_session.execute(
        insert(Document).values(_raw_document(tenant, record, "quote_deck_pptx", sha))
    )
    for purpose, why in (
        ("quote_deck_pptx", "the same bytes twice"),
        ("quote_deck_zip", "unknown"),
    ):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.execute(
                insert(Document).values(_raw_document(tenant, record, purpose, sha)),
            )
        assert why
    # The same bytes as a PDF deck are a different document: allowed.
    db_session.execute(insert(Document).values(_raw_document(tenant, record, "quote_deck", sha)))
