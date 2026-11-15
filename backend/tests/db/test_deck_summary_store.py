# ruff: noqa: F811 - pytest fixtures imported from the other deck tests are used as parameters
"""Approved "why this proposal" texts through the real database and the deck job (ADR 0032
Amendment A, PD7). The approval queue calls ``add_summary``; the deck job then draws the newest
approved text into the PDF and the PowerPoint. Uses the people and records of test_quotes_api.py."""

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.core.storage import MemoryFileStore
from app.modules.documents.models import Document
from app.modules.proposal_decks import api as decks_api
from app.modules.proposal_decks.models import DeckSummary
from app.modules.quotes import api as quotes_api
from tests.db.test_proposal_deck_api import (  # noqa: F401 - fixtures used by name
    approved,
    files,
    run_jobs,
)
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    QUOTES,
    Headers,
    World,
    api,
    auth,
    new_quote,
    ok,
    world,
)

SUMMARY = (
    "You wanted a quiet plot near the school; this one is 300 metres away and fits your budget."
)


def add(db_session: Session, world: World, quote: Any, body: str, user: str = "alpha.manager"):
    person = world.users[user]
    bind_tenant(db_session, person.tenant_id)
    return decks_api.add_summary(
        db_session, person.tenant_id, uuid.UUID(quote["id"]), body, person.id
    )


def ask(api: TestClient, auth: Headers, quote: Any, fmt: str) -> None:
    response = api.post(f"{QUOTES}/{quote['id']}/deck?format={fmt}", headers=auth("alpha.agent1"))
    assert response.status_code == 202


def newest(db_session: Session, quote: Any, purpose: str) -> Document:
    return db_session.scalars(
        select(Document)
        .where(Document.record_id == uuid.UUID(quote["id"]), Document.purpose == purpose)
        .order_by(Document.created_at.desc(), Document.id)
    ).first()  # type: ignore[return-value]


def pdf_text(files: MemoryFileStore, doc: Document) -> str:
    return "\n".join(
        p.extract_text() for p in PdfReader(io.BytesIO(files.get(doc.storage_key))).pages
    )


def pptx_text(files: MemoryFileStore, doc: Document) -> str:
    prs = Presentation(io.BytesIO(files.get(doc.storage_key)))
    return "\n".join(
        shape.text_frame.text for s in prs.slides for shape in s.shapes if shape.has_text_frame
    )


# --- storing and reading ---------------------------------------------------------------------


def test_an_approved_text_is_stored_and_the_newest_is_read(api, auth, world, db_session) -> None:
    quote = approved(api, auth, world)
    tenant = world.users["alpha.manager"].tenant_id
    assert decks_api.latest_summary(db_session, tenant, uuid.UUID(quote["id"])) is None
    add(db_session, world, quote, "  First version.  ")
    assert decks_api.latest_summary(db_session, tenant, uuid.UUID(quote["id"])) == "First version."
    add(db_session, world, quote, "Second version.")
    assert decks_api.latest_summary(db_session, tenant, uuid.UUID(quote["id"])) == "Second version."
    rows = db_session.scalars(select(DeckSummary).order_by(DeckSummary.seq)).all()
    assert [r.body for r in rows] == ["First version.", "Second version."]  # the old one stays
    assert rows[0].approved_by_user_id == world.users["alpha.manager"].id


@pytest.mark.parametrize(
    "body", ["", "   ", "word " * 121, "a" * 1001], ids=["empty", "blank", "words", "chars"]
)
def test_a_text_that_does_not_fit_the_slide_is_refused_and_nothing_is_stored(
    api, auth, world, db_session, body
) -> None:
    quote = approved(api, auth, world)
    with pytest.raises(decks_api.DeckSummaryInvalidError):
        add(db_session, world, quote, body)
    assert db_session.scalars(select(DeckSummary)).all() == []


def test_a_draft_quote_and_a_made_up_quote_cannot_have_a_summary(
    api, auth, world, db_session
) -> None:
    draft = new_quote(api, auth, world)
    with pytest.raises(quotes_api.QuoteNotReadyForDeckError):
        add(db_session, world, draft, SUMMARY)
    with pytest.raises(Exception, match="quote not found"):
        add(db_session, world, {"id": str(uuid.uuid4())}, SUMMARY)
    assert db_session.scalars(select(DeckSummary)).all() == []


def test_another_organisation_cannot_use_or_read_a_quotes_summary(
    api, auth, world, db_session
) -> None:
    quote = approved(api, auth, world)
    add(db_session, world, quote, SUMMARY)
    beta = world.users["beta.admin"]
    bind_tenant(db_session, beta.tenant_id)
    assert decks_api.latest_summary(db_session, beta.tenant_id, uuid.UUID(quote["id"])) is None
    with pytest.raises(Exception, match="quote not found"):
        decks_api.add_summary(db_session, beta.tenant_id, uuid.UUID(quote["id"]), SUMMARY, beta.id)


# --- the deck job draws it -------------------------------------------------------------------


def test_the_pdf_and_the_powerpoint_show_the_approved_text(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    add(db_session, world, quote, SUMMARY)
    ask(api, auth, quote, "pdf")
    ask(api, auth, quote, "pptx")
    run_jobs()
    pdf = pdf_text(files, newest(db_session, quote, "quote_deck"))
    assert "Why this proposal" in pdf and SUMMARY.split(";")[0] in pdf.replace("\n", " ")
    pptx = pptx_text(files, newest(db_session, quote, "quote_deck_pptx"))
    assert "Why this proposal" in pptx and SUMMARY in pptx


def test_without_an_approved_text_there_is_no_slide(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote, "pdf")
    run_jobs()
    assert "Why this proposal" not in pdf_text(files, newest(db_session, quote, "quote_deck"))


def test_a_new_approval_gives_a_new_deck_and_the_old_deck_stays(
    api, auth, world, files, run_jobs, db_session
) -> None:
    quote = approved(api, auth, world)
    ask(api, auth, quote, "pdf")
    run_jobs()
    before = newest(db_session, quote, "quote_deck")
    add(db_session, world, quote, "Fresh reasons for this proposal.")
    ask(api, auth, quote, "pdf")
    run_jobs()
    after = newest(db_session, quote, "quote_deck")
    assert after.id != before.id and after.sha256 != before.sha256
    assert "Fresh reasons" in pdf_text(files, after)
    assert "Fresh reasons" not in pdf_text(files, before)  # the earlier deck is untouched
    # Asking again with nothing new stores nothing new.
    ask(api, auth, quote, "pdf")
    run_jobs()
    assert newest(db_session, quote, "quote_deck").id == after.id


def test_a_summary_of_one_quote_never_appears_in_another_quotes_deck(
    api, auth, world, files, run_jobs, db_session
) -> None:
    mine, other = approved(api, auth, world), approved(api, auth, world)
    add(db_session, world, mine, "ONLY-FOR-THE-FIRST-QUOTE")
    ask(api, auth, other, "pptx")
    run_jobs()
    assert "ONLY-FOR-THE-FIRST-QUOTE" not in pptx_text(
        files, newest(db_session, other, "quote_deck_pptx")
    )


# --- what the database itself refuses --------------------------------------------------------


def test_the_database_refuses_to_change_or_delete_a_summary(api, auth, world, db_session) -> None:
    quote = approved(api, auth, world)
    summary_id = add(db_session, world, quote, SUMMARY)
    with pytest.raises(DBAPIError, match="permission denied"), db_session.begin_nested():
        db_session.execute(
            text("UPDATE deck_summaries SET body = 'x' WHERE id = :i"), {"i": summary_id}
        )
    with pytest.raises(DBAPIError, match="365 days"), db_session.begin_nested():
        db_session.execute(text("DELETE FROM deck_summaries WHERE id = :i"), {"i": summary_id})
    assert db_session.get(DeckSummary, summary_id) is not None
    # The application role is stopped by its missing privilege; the trigger also binds the owner.
    trigger = db_session.scalar(
        text("SELECT count(*) FROM pg_trigger WHERE tgname = 'deck_summaries_guard'")
    )
    assert trigger == 1


def test_the_database_checks_the_length_and_who_approved(api, auth, world, db_session) -> None:
    quote = approved(api, auth, world)
    tenant = world.users["alpha.manager"].tenant_id
    bind_tenant(db_session, tenant)
    base = {"tenant_id": tenant, "quote_id": uuid.UUID(quote["id"])}
    for body, approver in (
        ("", world.users["alpha.manager"].id),
        ("a" * 1001, world.users["alpha.manager"].id),
        ("fine", uuid.uuid4()),  # not a user of the organisation
    ):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(DeckSummary(**base, body=body, approved_by_user_id=approver))
            db_session.flush()
