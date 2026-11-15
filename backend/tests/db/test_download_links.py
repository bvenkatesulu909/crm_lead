# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Downloads by signed link (ADR 0025, step DU3a): the same access rules as the byte downloads,
then a 60-second link to the file in the store. Through the real API and PostgreSQL; the store is
the in-memory one, whose links look like ``memory://files/<key>?name=<file name>``."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote as urlquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import MemoryFileStore
from app.modules.documents.models import Document
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
    to_sent,
    world,
)

DOCS = "/api/v1/documents"
PORTAL_DOCS = "/api/v1/portal/documents"
PDF = b"%PDF-1.7 fictional offer"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


def upload(
    api: TestClient, auth: Headers, world: World, *, visible: bool = False, name: str = "offer.pdf"
) -> Any:
    response = api.post(
        DOCS,
        data={
            "record_type": "account",
            "record_id": str(world.ids["A1"]),
            "customer_visible": str(visible).lower(),
        },
        files={"file": (name, PDF, "application/pdf")},
        headers=auth("alpha.agent1"),
    )
    return ok(response, 201)


def link(api: TestClient, auth: Headers, path: str, user: str) -> Any:
    return api.get(path, headers=auth(user))


# --- documents (staff) ----------------------------------------------------------------------------


def test_a_reader_gets_a_short_link_to_the_stored_file(api, auth, world, files) -> None:
    doc = upload(api, auth, world)
    answer = ok(link(api, auth, f"{DOCS}/{doc['id']}/download-link", "alpha.agent1"))
    tenant = world.users["alpha.agent1"].tenant_id
    key = f"tenant/{tenant}/accounts/{world.ids['A1']}/{doc['id']}"
    assert answer["url"] == f"memory://files/{urlquote(key)}?name=offer.pdf"
    assert answer["file_name"] == "offer.pdf"
    expires = datetime.fromisoformat(answer["expires_at"])
    assert timedelta(seconds=50) < expires - datetime.now(UTC) <= timedelta(seconds=60)
    assert files.download_names[key] == "offer.pdf"  # the stored name, for SeaweedFS too


@pytest.mark.parametrize(
    ("user", "status"),
    [
        ("alpha.agent2", 404),  # a colleague's customer
        ("beta.agent", 404),  # another organisation
        ("alpha.customer", 403),  # customers use the portal address
    ],
)
def test_who_may_not_get_a_staff_link(api, auth, world, files, user, status) -> None:
    doc = upload(api, auth, world)
    assert link(api, auth, f"{DOCS}/{doc['id']}/download-link", user).status_code == status


def test_a_made_up_document_has_no_link(api, auth, world, files) -> None:
    path = f"{DOCS}/{uuid.uuid4()}/download-link"
    assert link(api, auth, path, "alpha.admin").status_code == 404


def test_a_missing_or_shortened_stored_file_gets_no_link(
    api, auth, world, files, db_session: Session
) -> None:
    doc = upload(api, auth, world)
    stored = db_session.scalars(select(Document).where(Document.id == uuid.UUID(doc["id"]))).one()
    files.objects[stored.storage_key] = (PDF[:5], "application/pdf")
    path = f"{DOCS}/{doc['id']}/download-link"
    assert code_of(link(api, auth, path, "alpha.agent1")) == (500, "document_integrity")
    del files.objects[stored.storage_key]
    assert link(api, auth, path, "alpha.agent1").status_code == 404


def test_without_a_file_store_there_is_no_link(api, auth, world, files) -> None:
    doc = upload(api, auth, world)
    from app.core.storage import UnconfiguredFileStore

    api.app.state.file_store = UnconfiguredFileStore()
    path = f"{DOCS}/{doc['id']}/download-link"
    assert code_of(link(api, auth, path, "alpha.agent1")) == (503, "files_unavailable")


# --- documents (portal) ---------------------------------------------------------------------------


def test_a_customer_gets_a_link_only_to_a_shared_newest_version(api, auth, world, files) -> None:
    hidden = upload(api, auth, world, name="internal.pdf")
    first = upload(api, auth, world, visible=True)
    newest = upload(api, auth, world, visible=True)  # same name: version 2
    path = PORTAL_DOCS + "/{}/download-link"
    assert ok(link(api, auth, path.format(newest["id"]), "alpha.customer"))["url"]
    for refused in (hidden["id"], first["id"]):
        assert link(api, auth, path.format(refused), "alpha.customer").status_code == 404
    assert link(api, auth, path.format(newest["id"]), "alpha.customer2").status_code == 404
    assert link(api, auth, path.format(newest["id"]), "alpha.agent1").status_code == 403


# --- quote PDFs ---------------------------------------------------------------------------------


def test_staff_get_a_link_to_the_pdf_of_a_sent_quote(api, auth, world, files) -> None:
    quote = to_sent(api, auth, world)
    answer = ok(link(api, auth, f"{QUOTES}/{quote['id']}/pdf-link", "alpha.agent1"))
    number = f"QT-{quote['number']:04d}.pdf"
    assert answer["file_name"] == number and answer["url"].endswith(f"?name={number}")
    [key] = files.objects  # generated once, on the first ask
    assert files.download_names[key] == number
    ok(link(api, auth, f"{QUOTES}/{quote['id']}/pdf-link", "alpha.manager"))
    assert len(files.objects) == 1


def test_no_pdf_link_before_the_quote_is_sent(api, auth, world, files) -> None:
    draft = new_quote(api, auth, world)
    path = f"{QUOTES}/{draft['id']}/pdf-link"
    assert code_of(link(api, auth, path, "alpha.agent1")) == (409, "quote_not_sent")


@pytest.mark.parametrize(
    ("user", "status"),
    [("alpha.agent2", 404), ("beta.admin", 404), ("alpha.support", 403), ("alpha.customer", 403)],
)
def test_who_may_not_get_a_staff_pdf_link(api, auth, world, files, user, status) -> None:
    quote = to_sent(api, auth, world)
    assert link(api, auth, f"{QUOTES}/{quote['id']}/pdf-link", user).status_code == status
    assert files.objects == {}  # nothing generated for refused callers


def test_customers_get_a_link_to_their_own_quote_pdf(api, auth, world, files) -> None:
    quote = to_sent(api, auth, world)
    path = f"{PORTAL}/{quote['id']}/pdf-link"
    assert ok(link(api, auth, path, "alpha.customer"))["url"].startswith("memory://files/")
    assert link(api, auth, path, "alpha.customer2").status_code == 404
    assert link(api, auth, path, "alpha.agent1").status_code == 403
