# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Adjusted photos in proposal decks (ADR 0039, PE5) through the real API, worker and PostgreSQL.

A sales person chooses finished copies for decks; the deck job then draws a photo slide with the
copies chosen for the quote's account or deal, each with the fixed caption. Nothing is drawn that
was not chosen. People and records come from test_quotes_api.py (agent1 owns A1 and deal O1).
"""

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.storage import MemoryFileStore
from app.modules.documents.models import Document
from app.modules.photo_enhancer import api as photo_api
from app.modules.photo_enhancer import rules
from tests.db.test_documents_api import upload
from tests.db.test_photo_enhancer import jpeg
from tests.db.test_photo_enhancer_api import BASE, on, photo, switch  # noqa: F401 - fixtures
from tests.db.test_proposal_deck_api import approved, files, run_jobs  # noqa: F401 - fixtures
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

CAPTION = rules.DECK_CAPTION


def make_copy(api: TestClient, auth: Headers, run_jobs: Any, doc: str, user="alpha.agent1") -> str:
    """Ask for an adjusted copy and let the worker make it; returns the request's id."""
    asked = ok(
        api.post(
            BASE + "/enhancements",
            json={"document_id": doc, "operations": {"brightness_percent": 10}},
            headers=auth(user),
        ),
        201,
    )
    run_jobs()
    return str(asked["id"])


def choose(api: TestClient, auth: Headers, copy_id: str, value: bool = True, user="alpha.agent1"):
    return api.patch(f"{BASE}/enhancements/{copy_id}", json={"in_decks": value}, headers=auth(user))


def deck_document(db_session: Session, quote: Any, purpose: str) -> Document:
    return db_session.scalars(
        select(Document)
        .where(Document.record_id == uuid.UUID(quote["id"]), Document.purpose == purpose)
        .order_by(Document.created_at.desc())
    ).first()  # type: ignore[return-value]


def make_deck(api: TestClient, auth: Headers, run_jobs: Any, quote: Any, fmt: str = "pdf") -> None:
    query = "" if fmt == "pdf" else "?format=pptx"
    assert (
        api.post(f"{QUOTES}/{quote['id']}/deck{query}", headers=auth("alpha.agent1")).status_code
        == 202
    )
    run_jobs()


def pdf_info(store: MemoryFileStore, doc: Document) -> tuple[list[str], int]:
    reader = PdfReader(io.BytesIO(store.get(doc.storage_key)))
    return [p.extract_text() for p in reader.pages], sum(len(p.images) for p in reader.pages)


def pptx_info(store: MemoryFileStore, doc: Document) -> tuple[list[str], int]:
    prs = Presentation(io.BytesIO(store.get(doc.storage_key)))
    texts = [
        "\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame)
        for slide in prs.slides
    ]
    pictures = sum(
        1
        for slide in prs.slides
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    )
    return texts, pictures


# --- choosing a copy -------------------------------------------------------------------------


def test_a_finished_copy_can_be_chosen_and_unchosen(api, auth, world, files, run_jobs, on) -> None:
    copy_id = make_copy(api, auth, run_jobs, photo(api, auth, world))
    assert ok(choose(api, auth, copy_id))["in_decks"] is True
    assert ok(choose(api, auth, copy_id, False))["in_decks"] is False


def test_a_new_copy_is_not_chosen_until_someone_chooses_it(
    api, auth, world, files, run_jobs, on
) -> None:
    doc = photo(api, auth, world)
    make_copy(api, auth, run_jobs, doc)
    [item] = ok(
        api.get(BASE + "/enhancements", params={"document_id": doc}, headers=auth("alpha.agent1"))
    )["items"]
    assert item["in_decks"] is False


def test_a_waiting_copy_cannot_be_chosen(api, auth, world, files, on) -> None:
    asked = ok(
        api.post(
            BASE + "/enhancements",
            json={"document_id": photo(api, auth, world), "operations": {}},
            headers=auth("alpha.agent1"),
        ),
        201,
    )
    assert code_of(choose(api, auth, asked["id"])) == (409, "photo_copy_not_ready")


def test_who_may_choose(api, auth, world, files, run_jobs, on) -> None:
    copy_id = make_copy(api, auth, run_jobs, photo(api, auth, world))
    switch(api, auth, admin="beta.admin")
    assert choose(api, auth, copy_id, user="alpha.support").status_code == 403
    assert choose(api, auth, copy_id, user="alpha.customer").status_code == 403
    assert choose(api, auth, copy_id, user="alpha.agent2").status_code == 404
    assert choose(api, auth, copy_id, user="beta.agent").status_code == 404
    assert choose(api, auth, str(uuid.uuid4())).status_code == 404
    assert choose(api, auth, copy_id, user="alpha.manager").status_code == 200


def test_the_body_takes_only_the_choice(api, auth, world, files, run_jobs, on) -> None:
    copy_id = make_copy(api, auth, run_jobs, photo(api, auth, world))
    for body in ({"in_decks": True, "status": "failed"}, {"in_decks": "yes"}, {}):
        response = api.patch(
            f"{BASE}/enhancements/{copy_id}", json=body, headers=auth("alpha.agent1")
        )
        assert response.status_code == 422


def test_the_choice_is_audited_without_the_picture(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    copy_id = make_copy(api, auth, run_jobs, photo(api, auth, world))
    choose(api, auth, copy_id)
    choose(api, auth, copy_id)  # no change, no second entry
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    rows = db_session.scalars(select(AuditLog).where(AuditLog.action == "photo.deck_choice")).all()
    assert len(rows) == 1 and rows[0].changes["in_decks"] is True


# --- the deck ----------------------------------------------------------------------------------


def test_a_chosen_copy_appears_in_the_pdf_deck_with_its_caption(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    quote = approved(api, auth, world)
    make_deck(api, auth, run_jobs, quote)
    before = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert not any("The property" in page for page in before[0])

    choose(api, auth, make_copy(api, auth, run_jobs, photo(api, auth, world)))
    make_deck(api, auth, run_jobs, quote)
    pages, images = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    [slide] = [p for p in pages if "The property" in p]
    assert CAPTION in slide
    assert images == before[1] + 1


def test_a_chosen_copy_appears_in_the_powerpoint_deck_too(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    quote = approved(api, auth, world)
    choose(api, auth, make_copy(api, auth, run_jobs, photo(api, auth, world)))
    make_deck(api, auth, run_jobs, quote, "pptx")
    texts, pictures = pptx_info(files, deck_document(db_session, quote, "quote_deck_pptx"))
    [slide] = [t for t in texts if "The property" in t]
    assert CAPTION in slide and pictures == 1


def test_a_copy_nobody_chose_is_never_drawn(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    make_copy(api, auth, run_jobs, photo(api, auth, world))  # made, but not chosen
    quote = approved(api, auth, world)
    make_deck(api, auth, run_jobs, quote)
    pages, _ = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert not any("The property" in p for p in pages)


def test_unchoosing_takes_the_photo_out_of_the_next_deck(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    quote = approved(api, auth, world)
    copy_id = make_copy(api, auth, run_jobs, photo(api, auth, world))
    choose(api, auth, copy_id)
    make_deck(api, auth, run_jobs, quote)
    choose(api, auth, copy_id, False)
    make_deck(api, auth, run_jobs, quote)
    pages, _ = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert not any("The property" in p for p in pages)


def test_only_the_quotes_own_account_and_deal_photos_are_used(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    # A2 belongs to agent2: a photo chosen there must never reach a quote of A1.
    other = ok(
        upload(
            api, auth, world, user="alpha.agent2", record="A2", name="other.jpg",
            data=jpeg(), mime="image/jpeg",
        ),
        201,
    )["id"]  # fmt: skip
    choose(api, auth, make_copy(api, auth, run_jobs, other, "alpha.agent2"), user="alpha.agent2")
    quote = approved(api, auth, world)
    make_deck(api, auth, run_jobs, quote)
    pages, _ = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert not any("The property" in p for p in pages)


def test_a_photo_on_the_quotes_deal_is_used(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    deal_photo = ok(
        upload(
            api, auth, world, record="O1", record_type="opportunity", name="deal.jpg",
            data=jpeg(), mime="image/jpeg",
        ),
        201,
    )["id"]  # fmt: skip
    choose(api, auth, make_copy(api, auth, run_jobs, deal_photo))
    with_deal = approved(api, auth, world, opportunity_id=str(world.ids["O1"]))
    without_deal = approved(api, auth, world)
    make_deck(api, auth, run_jobs, with_deal)
    make_deck(api, auth, run_jobs, without_deal)
    assert any(
        "The property" in p
        for p in pdf_info(files, deck_document(db_session, with_deal, "quote_deck"))[0]
    )
    assert not any(
        "The property" in p
        for p in pdf_info(files, deck_document(db_session, without_deal, "quote_deck"))[0]
    )


def test_at_most_four_photos_are_drawn(api, auth, world, files, run_jobs, on, db_session) -> None:
    quote = approved(api, auth, world)
    make_deck(api, auth, run_jobs, quote)
    base = pdf_info(files, deck_document(db_session, quote, "quote_deck"))[1]
    for index in range(5):
        doc = ok(
            upload(
                api, auth, world, name=f"p{index}.jpg", data=jpeg((200 + index, 150)),
                mime="image/jpeg",
            ),
            201,
        )["id"]  # fmt: skip
        choose(api, auth, make_copy(api, auth, run_jobs, doc))
    make_deck(api, auth, run_jobs, quote)
    pages, images = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert images == base + 4
    [slide] = [p for p in pages if "The property" in p]
    assert slide.count(CAPTION) == 4


def test_a_copy_that_lost_its_label_is_skipped(
    api, auth, world, files, run_jobs, on, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    choose(api, auth, make_copy(api, auth, run_jobs, photo(api, auth, world)))
    monkeypatch.setattr("app.modules.photo_enhancer.service.rules.has_label", lambda data: False)
    quote = approved(api, auth, world)
    make_deck(api, auth, run_jobs, quote)
    pages, _ = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert not any("The property" in p for p in pages)


def test_a_chosen_copy_whose_file_vanished_is_skipped_not_fatal(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    doc = photo(api, auth, world)
    copy_id = make_copy(api, auth, run_jobs, doc)
    choose(api, auth, copy_id)
    [derived] = db_session.scalars(
        select(Document).where(Document.purpose == "property_photo_enhanced")
    ).all()
    files.objects.pop(derived.storage_key)
    quote = approved(api, auth, world)
    make_deck(api, auth, run_jobs, quote)
    pages, _ = pdf_info(files, deck_document(db_session, quote, "quote_deck"))
    assert pages and not any("The property" in p for p in pages)


def test_the_service_stops_at_the_limit_it_is_given(
    api, auth, world, files, run_jobs, on, db_session
) -> None:
    for index in range(3):
        doc = ok(
            upload(
                api, auth, world, name=f"q{index}.jpg", data=jpeg((220 + index, 150)),
                mime="image/jpeg",
            ),
            201,
        )["id"]  # fmt: skip
        choose(api, auth, make_copy(api, auth, run_jobs, doc))
    tenant_id = world.users["alpha.agent1"].tenant_id
    bind_tenant(db_session, tenant_id)
    found = photo_api.deck_photos(
        db_session, files, tenant_id, account_id=world.ids["A1"], opportunity_id=None, limit=2
    )
    assert len(found) == 2 and all(p.caption == CAPTION for p in found)
