# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Phase 10 - documents on accounts and deals, through the real API and PostgreSQL.

People and records come from test_quotes_api.py: agent1 owns A1 and deal O1, agent2 owns A2,
customer -> A1, customer2 -> A2, tenant beta has B1. Files go to an in-memory store.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.storage import MemoryFileStore
from app.modules.documents.models import Document
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    Headers,
    World,
    api,
    auth,
    code_of,
    ok,
    world,
)

DOCS = "/api/v1/documents"
PORTAL = "/api/v1/portal/documents"
PDF = b"%PDF-1.7 fictional offer"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


def upload(
    api: TestClient,
    auth: Headers,
    world: World,
    *,
    user: str = "alpha.agent1",
    record: str = "A1",
    record_type: str = "account",
    name: str = "offer.pdf",
    data: bytes = PDF,
    mime: str = "application/pdf",
    **form: Any,
) -> Any:
    return api.post(
        DOCS,
        data={"record_type": record_type, "record_id": str(world.ids[record]), **form},
        files={"file": (name, data, mime)},
        headers=auth(user),
    )


def listing(api, auth, world, user="alpha.agent1", record="A1", record_type="account") -> Any:
    return api.get(
        DOCS,
        params={"record_type": record_type, "record_id": str(world.ids[record])},
        headers=auth(user),
    )


def test_upload_list_and_download(api, auth, world, files) -> None:
    doc = ok(upload(api, auth, world, description="Signed framework agreement"), 201)
    assert (doc["file_name"], doc["content_type"], doc["version_no"], doc["versions"]) == (
        "offer.pdf",
        "application/pdf",
        1,
        1,
    )
    assert doc["created_by_name"] == "alpha.agent1"
    tenant = world.users["alpha.agent1"].tenant_id
    [key] = files.objects
    assert key == f"tenant/{tenant}/accounts/{world.ids['A1']}/{doc['id']}"

    items = ok(listing(api, auth, world))["items"]
    assert [d["id"] for d in items] == [doc["id"]]

    response = api.get(f"{DOCS}/{doc['id']}/download", headers=auth("alpha.agent1"))
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-disposition"] == 'attachment; filename="offer.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"


def test_same_name_adds_a_version(api, auth, world, files) -> None:
    first = ok(upload(api, auth, world), 201)
    second = ok(upload(api, auth, world, name="OFFER.pdf", data=PDF + b" v2"), 201)
    assert (second["version_no"], second["group_id"]) == (2, first["group_id"])
    [item] = ok(listing(api, auth, world))["items"]
    assert (item["id"], item["versions"]) == (second["id"], 2)
    versions = ok(api.get(f"{DOCS}/{second['id']}/versions", headers=auth("alpha.agent1")))
    assert [v["version_no"] for v in versions["items"]] == [2, 1]
    old = api.get(f"{DOCS}/{first['id']}/download", headers=auth("alpha.agent1"))
    assert old.content == PDF  # older versions stay available to staff
    other = ok(upload(api, auth, world, name="price-list.pdf"), 201)
    assert other["version_no"] == 1 and other["group_id"] != first["group_id"]


@pytest.mark.parametrize(
    ("name", "data", "mime", "expected"),
    [
        ("tool.exe", b"MZ\x90\x00", "application/octet-stream", (415, "file_type_not_allowed")),
        ("page.html", b"<script>alert(1)</script>", "text/html", (415, "file_type_not_allowed")),
        ("fake.pdf", b"\x89PNG\r\n\x1a\n", "application/pdf", (415, "file_type_not_allowed")),
        ("empty.pdf", b"", "application/pdf", (422, "invalid_document")),
    ],
)
def test_only_allowed_files(api, auth, world, files, name, data, mime, expected) -> None:
    assert code_of(upload(api, auth, world, name=name, data=data, mime=mime)) == expected
    assert files.objects == {}


def test_size_limit(api, auth, world, files) -> None:
    api.app.state.settings = api.app.state.settings.model_copy(update={"files_max_bytes": 1024})
    big = upload(api, auth, world, data=PDF + b"x" * 2000)
    assert code_of(big) == (413, "file_too_large")
    assert ok(upload(api, auth, world, data=PDF), 201)


def test_names_are_cleaned_and_the_browser_type_is_ignored(api, auth, world, files) -> None:
    doc = ok(upload(api, auth, world, name="..\\..\\evil<script>.pdf", mime="text/html"), 201)
    assert (doc["file_name"], doc["content_type"]) == ("evil_script_.pdf", "application/pdf")


@pytest.mark.parametrize("user", ["alpha.agent2", "beta.admin"])
def test_people_who_cannot_see_the_record_get_404(api, auth, world, files, user) -> None:
    doc = ok(upload(api, auth, world), 201)
    assert code_of(upload(api, auth, world, user=user)) == (404, "record_not_found")
    assert code_of(listing(api, auth, world, user=user)) == (404, "record_not_found")
    for path in (f"{DOCS}/{doc['id']}/download", f"{DOCS}/{doc['id']}/versions"):
        assert code_of(api.get(path, headers=auth(user))) == (404, "document_not_found")
    assert api.delete(f"{DOCS}/{doc['id']}", headers=auth("beta.admin")).status_code == 404


def test_tampered_ids_and_types(api, auth, world, files) -> None:
    random_record = api.post(
        DOCS,
        data={"record_type": "account", "record_id": str(uuid.uuid4())},
        files={"file": ("a.pdf", PDF, "application/pdf")},
        headers=auth("alpha.admin"),
    )
    assert code_of(random_record) == (404, "record_not_found")
    assert upload(api, auth, world, record_type="quote").status_code == 422
    assert (
        api.get(f"{DOCS}/{uuid.uuid4()}/download", headers=auth("alpha.admin")).status_code == 404
    )
    sneaky = upload(api, auth, world, tenant_id=str(uuid.uuid4()), created_by_user_id="x")
    assert ok(sneaky, 201)["created_by_name"] == "alpha.agent1"  # extra form fields are ignored


def test_roles(api, auth, world, files) -> None:
    doc = ok(upload(api, auth, world), 201)
    # Support reads documents of all accounts, but doesn't upload or delete.
    assert listing(api, auth, world, user="alpha.support").status_code == 200
    assert upload(api, auth, world, user="alpha.support").status_code == 403
    # Customers never use the staff endpoints.
    assert listing(api, auth, world, user="alpha.customer").status_code == 403
    # Agents upload, but only managers and admins delete.
    assert api.delete(f"{DOCS}/{doc['id']}", headers=auth("alpha.agent1")).status_code == 403
    assert api.delete(f"{DOCS}/{doc['id']}", headers=auth("alpha.manager")).status_code == 204


def test_delete_removes_every_version_and_file(
    api, auth, world, files, db_session: Session
) -> None:
    first = ok(upload(api, auth, world), 201)
    ok(upload(api, auth, world, data=PDF + b" v2"), 201)
    assert len(files.objects) == 2
    assert api.delete(f"{DOCS}/{first['id']}", headers=auth("alpha.admin")).status_code == 204
    assert ok(listing(api, auth, world))["items"] == []
    assert files.objects == {}
    actions = db_session.scalars(
        select(AuditLog.action).where(AuditLog.action.like("document.%"))
    ).all()
    assert sorted(actions) == ["document.deleted", "document.uploaded", "document.uploaded"]


def test_deal_documents_follow_the_deal(api, auth, world, files) -> None:
    doc = ok(upload(api, auth, world, record="O1", record_type="opportunity"), 201)
    assert (
        ok(listing(api, auth, world, record="O1", record_type="opportunity"))["items"][0]["id"]
        == doc["id"]
    )
    assert (
        listing(
            api, auth, world, user="alpha.agent2", record="O1", record_type="opportunity"
        ).status_code
        == 404
    )
    shown = upload(
        api, auth, world, record="O1", record_type="opportunity", customer_visible="true"
    )
    assert code_of(shown) == (422, "invalid_document")  # deal files are internal


def test_customers_see_only_shared_newest_versions(api, auth, world, files) -> None:
    shared = ok(upload(api, auth, world, name="terms.pdf", customer_visible="true"), 201)
    internal = ok(upload(api, auth, world, name="notes.pdf"), 201)
    mine = ok(
        api.get(PORTAL, params={"account_id": str(world.ids["A1"])}, headers=auth("alpha.customer"))
    )
    assert [d["id"] for d in mine["items"]] == [shared["id"]]
    assert set(mine["items"][0]) == {
        "id",
        "file_name",
        "content_type",
        "size_bytes",
        "version_no",
        "created_at",
    }
    download = api.get(f"{PORTAL}/{shared['id']}/download", headers=auth("alpha.customer"))
    assert download.status_code == 200 and download.content == PDF
    assert (
        api.get(f"{PORTAL}/{internal['id']}/download", headers=auth("alpha.customer")).status_code
        == 404
    )

    # Another customer, another account: nothing.
    other = api.get(
        PORTAL, params={"account_id": str(world.ids["A1"])}, headers=auth("alpha.customer2")
    )
    assert other.status_code == 404
    assert (
        api.get(f"{PORTAL}/{shared['id']}/download", headers=auth("alpha.customer2")).status_code
        == 404
    )
    # Staff tokens don't work on the portal.
    assert (
        api.get(
            PORTAL, params={"account_id": str(world.ids["A1"])}, headers=auth("alpha.agent1")
        ).status_code
        == 403
    )

    # A newer internal version hides the document, including its older shared version.
    ok(upload(api, auth, world, name="terms.pdf", data=PDF + b" draft"), 201)
    mine = ok(
        api.get(PORTAL, params={"account_id": str(world.ids["A1"])}, headers=auth("alpha.customer"))
    )
    assert mine["items"] == []
    assert (
        api.get(f"{PORTAL}/{shared['id']}/download", headers=auth("alpha.customer")).status_code
        == 404
    )


def test_without_a_file_store_uploads_answer_503(api, auth, world, db_session) -> None:
    assert code_of(upload(api, auth, world)) == (503, "files_unavailable")
    assert db_session.scalars(select(Document)).all() == []


def test_quote_pdfs_are_not_served_here(api, auth, world, files, db_session) -> None:
    tenant = world.users["alpha.agent1"].tenant_id
    pdf_id = uuid.uuid4()
    db_session.add(
        Document(
            id=pdf_id, tenant_id=tenant, record_type="quote", record_id=uuid.uuid4(),
            purpose="quote_pdf", file_name="QT-0001.pdf", content_type="application/pdf",
            size_bytes=3, sha256="0" * 64, storage_key=f"tenant/{tenant}/quotes/x/{pdf_id}",
            group_id=pdf_id,
        )
    )  # fmt: skip
    db_session.flush()
    assert api.get(f"{DOCS}/{pdf_id}/download", headers=auth("alpha.admin")).status_code == 404
