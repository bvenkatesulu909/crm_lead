# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Direct uploads (ADR 0025, step DU2): start -> the browser sends the file to the store -> finish.

Through the real API and PostgreSQL; the file store is the in-memory one, whose ``browser_upload``
refuses exactly what a real store refuses for a signed POST policy (another key, a bigger body).
People and records come from test_quotes_api.py: agent1 owns A1 and deal O1, agent2 owns A2,
beta.agent owns B1 in another organisation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.storage import MemoryFileStore, pending_key
from app.modules.documents import uploads
from app.modules.documents.models import Document, DocumentUpload
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
PDF = b"%PDF-1.7 a fictional brochure"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


@pytest.fixture
def settings_override(api: TestClient):  # noqa: ANN201
    """Change the API's settings for one test and put them back afterwards."""
    original = api.app.state.settings  # type: ignore[attr-defined]

    def change(**values: Any) -> None:
        api.app.state.settings = original.model_copy(update=values)  # type: ignore[attr-defined]

    yield change
    api.app.state.settings = original  # type: ignore[attr-defined]


def start(
    api: TestClient,
    auth: Headers,
    world: World,
    *,
    user: str = "alpha.agent1",
    record: str = "A1",
    record_type: str = "account",
    name: str = "brochure.pdf",
    size: int = len(PDF),
    **extra: Any,
) -> Any:
    body = {
        "record_type": record_type,
        "record_id": str(world.ids[record]),
        "file_name": name,
        "size_bytes": size,
        **extra,
    }
    return api.post(f"{DOCS}/uploads", json=body, headers=auth(user))


def finish(api: TestClient, auth: Headers, upload_id: str, user: str = "alpha.agent1") -> Any:
    return api.post(f"{DOCS}/uploads/{upload_id}/finish", headers=auth(user))


def count(db_session: Session, world: World, model: Any) -> int:
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    return int(db_session.scalar(select(func.count()).select_from(model)) or 0)


# --- the happy path -----------------------------------------------------------------------------


def test_a_file_sent_straight_to_the_store_becomes_a_document(
    api, auth, world, files, db_session
) -> None:
    ticket = ok(start(api, auth, world, description="Phase 2 brochure"), 201)
    tenant = world.users["alpha.agent1"].tenant_id
    key = pending_key(tenant, uuid.UUID(ticket["upload_id"]))
    assert ticket["fields"]["key"] == key
    assert ticket["fields"]["Content-Type"] == "application/pdf"
    assert ticket["max_bytes"] == len(PDF)
    assert files.signed_uploads[key] == ("application/pdf", len(PDF))
    assert count(db_session, world, Document) == 0  # nothing is a document before finish

    assert files.browser_upload(key, PDF) is True
    doc = ok(finish(api, auth, ticket["upload_id"]), 201)
    assert (doc["file_name"], doc["content_type"], doc["size_bytes"], doc["version_no"]) == (
        "brochure.pdf",
        "application/pdf",
        len(PDF),
        1,
    )
    assert doc["description"] == "Phase 2 brochure"
    final = f"tenant/{tenant}/accounts/{world.ids['A1']}/{doc['id']}"
    assert set(files.objects) == {final}  # the pending file is gone
    assert files.download_names[final] == "brochure.pdf"
    assert api.get(f"{DOCS}/{doc['id']}/download", headers=auth("alpha.agent1")).content == PDF
    bind_tenant(db_session, tenant)
    audited = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "document.uploaded")
    ).all()
    assert len(audited) == 1
    row = db_session.get(DocumentUpload, uuid.UUID(ticket["upload_id"]))
    assert row is not None and (row.status, str(row.document_id)) == ("finished", doc["id"])


def test_the_same_name_adds_a_version_as_before(api, auth, world, files) -> None:
    for version, body in ((1, PDF), (2, PDF + b" - second edition")):
        ticket = ok(start(api, auth, world, size=len(body)), 201)
        assert files.browser_upload(ticket["fields"]["key"], body) is True
        doc = ok(finish(api, auth, ticket["upload_id"]), 201)
        assert (doc["version_no"], doc["size_bytes"]) == (version, len(body))


def test_a_customer_visible_account_document_reaches_the_portal(api, auth, world, files) -> None:
    ticket = ok(start(api, auth, world, customer_visible=True), 201)
    files.browser_upload(ticket["fields"]["key"], PDF)
    ok(finish(api, auth, ticket["upload_id"]), 201)
    portal = api.get(
        "/api/v1/portal/documents",
        params={"account_id": str(world.ids["A1"])},
        headers=auth("alpha.customer"),
    )
    assert [d["file_name"] for d in ok(portal)["items"]] == ["brochure.pdf"]


# --- what start refuses ------------------------------------------------------------------------


def test_only_account_documents_can_be_shown_to_customers(api, auth, world, files) -> None:
    response = start(
        api, auth, world, record="O1", record_type="opportunity", customer_visible=True
    )
    assert response.status_code == 422 and files.signed_uploads == {}


def test_a_file_bigger_than_the_limit_is_refused_before_any_link(api, auth, world, files) -> None:
    response = start(api, auth, world, size=20 * 1024 * 1024 + 1)
    assert code_of(response) == (413, "file_too_large")
    assert files.signed_uploads == {}


@pytest.mark.parametrize("size", [0, -5])
def test_an_empty_or_negative_size_is_refused(api, auth, world, files, size) -> None:
    assert start(api, auth, world, size=size).status_code == 422


@pytest.mark.parametrize("name", ["setup.exe", "page.html", "script.js", "no-extension"])
def test_a_type_not_allowed_by_name_gets_no_link(api, auth, world, files, name) -> None:
    response = start(api, auth, world, name=name)
    assert code_of(response) == (415, "file_type_not_allowed")
    assert files.signed_uploads == {}


def test_the_browser_cannot_choose_the_tenant_or_the_key(api, auth, world, files) -> None:
    other = world.users["beta.agent"].tenant_id
    extras: list[dict[str, Any]] = [{"tenant_id": str(other)}, {"key": "tenant/x/accounts/y/z"}]
    for extra in extras:
        assert start(api, auth, world, **extra).status_code == 422
    assert files.signed_uploads == {}


@pytest.mark.parametrize(
    ("user", "record", "status"),
    [
        ("alpha.agent1", "A2", 404),  # a colleague's account
        ("alpha.agent1", "B1", 404),  # another organisation's account
        ("alpha.support", "A1", 403),  # no document:write
        ("alpha.customer", "A1", 403),  # a portal customer
    ],
)
def test_who_may_start_an_upload(api, auth, world, files, user, record, status) -> None:
    assert start(api, auth, world, user=user, record=record).status_code == status
    assert files.signed_uploads == {}


def test_a_made_up_record_is_not_found(api, auth, world, files) -> None:
    body = {
        "record_type": "account",
        "record_id": str(uuid.uuid4()),
        "file_name": "a.pdf",
        "size_bytes": 10,
    }
    response = api.post(f"{DOCS}/uploads", json=body, headers=auth("alpha.agent1"))
    assert response.status_code == 404


def test_one_person_has_an_hourly_limit(api, auth, world, files, settings_override) -> None:
    settings_override(files_uploads_per_user_hour=2)
    for _ in range(2):
        ok(start(api, auth, world), 201)
    response = start(api, auth, world)
    assert code_of(response) == (429, "upload_limit_reached")
    ok(start(api, auth, world, user="alpha.agent2", record="A2"), 201)  # per person


# --- what finish refuses -----------------------------------------------------------------------


def test_finish_before_the_file_arrived_says_so_and_can_be_retried(api, auth, world, files) -> None:
    ticket = ok(start(api, auth, world), 201)
    response = finish(api, auth, ticket["upload_id"])
    assert code_of(response) == (409, "upload_not_received")
    files.browser_upload(ticket["fields"]["key"], PDF)
    ok(finish(api, auth, ticket["upload_id"]), 201)


def test_a_body_bigger_than_announced_never_arrives(api, auth, world, files) -> None:
    ticket = ok(start(api, auth, world, size=10), 201)
    assert files.browser_upload(ticket["fields"]["key"], PDF) is False  # the store refuses it
    assert code_of(finish(api, auth, ticket["upload_id"])) == (409, "upload_not_received")


def test_a_file_bigger_than_announced_is_refused_even_if_a_store_took_it(
    api, auth, world, files
) -> None:
    # A store that signs only PUT would not enforce the size: finish checks it again.
    ticket = ok(start(api, auth, world, size=10), 201)
    files.put(ticket["fields"]["key"], PDF, "application/pdf")
    response = finish(api, auth, ticket["upload_id"])
    assert code_of(response) == (413, "file_too_large")
    assert files.objects == {}


def test_a_disguised_file_is_refused_and_not_kept(api, auth, world, files, db_session) -> None:
    html = b"<html><script>alert(1)</script></html>"
    ticket = ok(start(api, auth, world, size=len(html)), 201)  # named brochure.pdf
    files.browser_upload(ticket["fields"]["key"], html)
    response = finish(api, auth, ticket["upload_id"])
    assert code_of(response) == (415, "file_type_not_allowed")
    assert files.objects == {} and count(db_session, world, Document) == 0


def test_an_empty_file_is_refused(api, auth, world, files) -> None:
    ticket = ok(start(api, auth, world), 201)
    files.objects[ticket["fields"]["key"]] = (b"", "application/pdf")
    assert finish(api, auth, ticket["upload_id"]).status_code == 422


@pytest.mark.parametrize("finisher", ["alpha.agent2", "alpha.manager", "beta.agent"])
def test_nobody_else_can_finish_my_upload(api, auth, world, files, finisher) -> None:
    ticket = ok(start(api, auth, world), 201)
    files.browser_upload(ticket["fields"]["key"], PDF)
    response = finish(api, auth, ticket["upload_id"], user=finisher)
    assert code_of(response) == (404, "upload_not_found")
    ok(finish(api, auth, ticket["upload_id"]), 201)  # still mine to finish


def test_finishing_twice_makes_one_document(api, auth, world, files, db_session) -> None:
    ticket = ok(start(api, auth, world), 201)
    files.browser_upload(ticket["fields"]["key"], PDF)
    ok(finish(api, auth, ticket["upload_id"]), 201)
    assert finish(api, auth, ticket["upload_id"]).status_code == 404
    assert count(db_session, world, Document) == 1


def test_a_made_up_upload_id_is_not_found(api, auth, world, files) -> None:
    assert finish(api, auth, str(uuid.uuid4())).status_code == 404


def test_access_lost_before_finish_means_no_document(api, auth, world, files, db_session) -> None:
    """finish checks the record again: someone whose access ended cannot complete an upload."""
    ticket = ok(start(api, auth, world, user="alpha.manager", record="A1"), 201)
    files.browser_upload(ticket["fields"]["key"], PDF)
    from app.modules.accounts.models import Account

    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    # The upload's record is deleted (soft) before finish: the record check refuses it.
    account = db_session.get(Account, world.ids["A1"])
    assert account is not None
    account.deleted_at = datetime.now(UTC)
    db_session.commit()
    assert finish(api, auth, ticket["upload_id"], user="alpha.manager").status_code == 404


def test_a_late_finish_expires(api, auth, world, files, db_session) -> None:
    ticket = ok(start(api, auth, world), 201)
    files.browser_upload(ticket["fields"]["key"], PDF)
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    row = db_session.get(DocumentUpload, uuid.UUID(ticket["upload_id"]))
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()
    response = finish(api, auth, ticket["upload_id"])
    assert code_of(response) == (410, "upload_expired")
    assert files.objects == {}


# --- the clean-up sweep ------------------------------------------------------------------------


def test_the_sweep_removes_day_old_uploads_and_their_files(
    api, auth, world, files, db_session
) -> None:
    old = ok(start(api, auth, world), 201)
    fresh = ok(start(api, auth, world), 201)
    for ticket in (old, fresh):
        files.browser_upload(ticket["fields"]["key"], PDF)
    tenant = world.users["alpha.agent1"].tenant_id
    bind_tenant(db_session, tenant)
    row = db_session.get(DocumentUpload, uuid.UUID(old["upload_id"]))
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(days=2)
    db_session.flush()
    removed = uploads.delete_stale_uploads(db_session, files, datetime.now(UTC), tenant_id=tenant)
    assert removed == 1
    assert old["fields"]["key"] not in files.objects and fresh["fields"]["key"] in files.objects
    assert db_session.get(DocumentUpload, uuid.UUID(old["upload_id"])) is None


def test_another_organisation_never_sees_my_pending_uploads(
    api, auth, world, files, db_session
) -> None:
    ok(start(api, auth, world), 201)
    bind_tenant(db_session, world.users["beta.agent"].tenant_id)
    assert db_session.scalar(select(func.count()).select_from(DocumentUpload)) == 0
