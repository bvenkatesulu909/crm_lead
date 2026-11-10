# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Direct uploads of knowledge documents (ADR 0025, step DU3b): start -> the browser sends the
file to the store -> finish, which indexes it exactly like a normal knowledge upload.

Through the real API and PostgreSQL; the store is the in-memory one, whose ``browser_upload``
refuses what a real store refuses for a signed POST policy (another key, a bigger body).
alpha.admin is a tenant admin (knowledge:manage), alpha.agent1 a sales agent (read only),
beta.admin another organisation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.core.storage import MemoryFileStore, pending_key
from app.modules.knowledge import uploads
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeUpload
from tests.db.test_knowledge_api import TEXT, run_ingest
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    Headers,
    World,
    api,
    auth,
    code_of,
    ok,
    world,
)

KB = "/api/v1/knowledge"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


def start(
    api: TestClient,
    auth: Headers,
    *,
    user: str = "alpha.admin",
    name: str = "returns.txt",
    size: int = len(TEXT),
    **extra: Any,
) -> Any:
    body = {"file_name": name, "size_bytes": size, **extra}
    return api.post(f"{KB}/uploads", json=body, headers=auth(user))


def finish(api: TestClient, auth: Headers, upload_id: str, user: str = "alpha.admin") -> Any:
    return api.post(f"{KB}/uploads/{upload_id}/finish", headers=auth(user))


def documents(db_session: Session, world: World) -> int:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    return int(db_session.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0)


def test_a_file_sent_straight_to_the_store_is_indexed(api, auth, world, files, db_session) -> None:
    ticket = ok(start(api, auth, title="Returns"), 201)
    tenant = world.users["alpha.admin"].tenant_id
    key = pending_key(tenant, uuid.UUID(ticket["upload_id"]))
    assert ticket["fields"]["key"] == key and ticket["fields"]["Content-Type"] == "text/plain"
    assert files.signed_uploads[key] == ("text/plain", len(TEXT))
    assert documents(db_session, world) == 0

    assert files.browser_upload(key, TEXT) is True
    created = ok(finish(api, auth, ticket["upload_id"]), 201)
    assert (created["title"], created["status"]) == ("Returns", "processing")
    assert key not in files.objects  # the pending file is gone
    run_ingest(files, db_session, created["id"])  # the normal indexing job was queued
    indexed = ok(api.get(f"{KB}/documents/{created['id']}", headers=auth("alpha.admin")))
    assert indexed["status"] == "indexed" and indexed["chunk_count"] >= 1


def test_a_new_version_replaces_the_previous_one(api, auth, world, files, db_session) -> None:
    first = ok(start(api, auth), 201)
    files.browser_upload(first["fields"]["key"], TEXT)
    old = ok(finish(api, auth, first["upload_id"]), 201)
    body = b"# Returns\n\nUpdated window: 21 days.\n"
    second = ok(start(api, auth, size=len(body), replaces_document_id=old["id"]), 201)
    files.browser_upload(second["fields"]["key"], body)
    new = ok(finish(api, auth, second["upload_id"]), 201)
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    previous = db_session.get(KnowledgeDocument, uuid.UUID(old["id"]))
    assert previous is not None and previous.is_archived is True
    assert new["version"] == 2


def test_the_same_content_twice_is_a_duplicate_and_not_kept(api, auth, world, files) -> None:
    first = ok(start(api, auth), 201)
    files.browser_upload(first["fields"]["key"], TEXT)
    ok(finish(api, auth, first["upload_id"]), 201)
    again = ok(start(api, auth, name="returns-copy.txt"), 201)
    files.browser_upload(again["fields"]["key"], TEXT)
    response = finish(api, auth, again["upload_id"])
    assert response.status_code == 409
    assert again["fields"]["key"] not in files.objects


# --- what start refuses ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({"visibility": "public"}, 422),
        ({"account_id": str(uuid.uuid4())}, 422),  # internal + an account
        ({"visibility": "customer_visible", "account_id": str(uuid.uuid4())}, 422),
        ({"replaces_document_id": str(uuid.uuid4())}, 422),
        ({"size": 20 * 1024 * 1024 + 1}, 413),
        ({"name": "slides.pptx"}, 415),
        ({"tenant_id": str(uuid.uuid4())}, 422),
    ],
)
def test_start_refuses_before_any_link(api, auth, world, files, extra, status) -> None:
    size = extra.pop("size", len(TEXT))
    name = extra.pop("name", "returns.txt")
    assert start(api, auth, size=size, name=name, **extra).status_code == status
    assert files.signed_uploads == {}


def test_an_internal_document_is_never_linked_to_a_readable_account(
    api, auth, world, files
) -> None:
    # The account exists and the admin may read it: only the internal rule refuses this.
    response = start(api, auth, account_id=str(world.ids["A1"]))
    assert response.status_code == 422
    assert files.signed_uploads == {}
    ok(start(api, auth, visibility="customer_visible", account_id=str(world.ids["A1"])), 201)


@pytest.mark.parametrize(
    ("user", "status"), [("alpha.agent1", 403), ("alpha.customer", 403), ("alpha.support", 403)]
)
def test_only_knowledge_managers_may_start(api, auth, world, files, user, status) -> None:
    assert start(api, auth, user=user).status_code == status


def test_one_person_has_an_hourly_limit(api, auth, world, files) -> None:
    original = api.app.state.settings
    api.app.state.settings = original.model_copy(update={"files_uploads_per_user_hour": 1})
    try:
        ok(start(api, auth), 201)
        assert code_of(start(api, auth)) == (429, "upload_limit_reached")
    finally:
        api.app.state.settings = original


# --- what finish refuses -----------------------------------------------------------------------


def test_finish_before_the_file_arrived_can_be_retried(api, auth, world, files) -> None:
    ticket = ok(start(api, auth), 201)
    assert code_of(finish(api, auth, ticket["upload_id"])) == (409, "upload_not_received")
    files.browser_upload(ticket["fields"]["key"], TEXT)
    ok(finish(api, auth, ticket["upload_id"]), 201)


def test_a_file_bigger_than_announced_is_refused(api, auth, world, files) -> None:
    ticket = ok(start(api, auth, size=10), 201)
    files.put(ticket["fields"]["key"], TEXT, "text/plain")  # a store that did not enforce it
    assert code_of(finish(api, auth, ticket["upload_id"])) == (413, "file_too_large")
    assert files.objects == {}


def test_a_disguised_file_is_refused_and_not_kept(api, auth, world, files, db_session) -> None:
    binary = b"\x00\x01\x02 not text"
    ticket = ok(start(api, auth, size=len(binary)), 201)  # named returns.txt
    files.browser_upload(ticket["fields"]["key"], binary)
    assert finish(api, auth, ticket["upload_id"]).status_code == 415
    assert files.objects == {} and documents(db_session, world) == 0


@pytest.mark.parametrize(
    ("finisher", "expected"),
    [
        ("beta.admin", (404, "upload_not_found")),  # another organisation's knowledge manager
        ("alpha.manager", (403, None)),  # no knowledge:manage at all - refused at the door
    ],
)
def test_nobody_else_can_finish_my_upload(api, auth, world, files, finisher, expected) -> None:
    ticket = ok(start(api, auth), 201)
    files.browser_upload(ticket["fields"]["key"], TEXT)
    assert code_of(finish(api, auth, ticket["upload_id"], finisher)) == expected
    ok(finish(api, auth, ticket["upload_id"]), 201)


def test_a_colleague_in_the_same_organisation_cannot_finish_it(
    api, auth, world, files, db_session
) -> None:
    # Same organisation and the same permission: only the "started by this person" rule refuses.
    ticket = ok(start(api, auth), 201)
    files.browser_upload(ticket["fields"]["key"], TEXT)
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    row = db_session.get(KnowledgeUpload, uuid.UUID(ticket["upload_id"]))
    assert row is not None
    row.created_by_user_id = world.users["alpha.manager"].id  # as if a colleague had started it
    db_session.commit()
    assert code_of(finish(api, auth, ticket["upload_id"])) == (404, "upload_not_found")
    assert documents(db_session, world) == 0


def test_finishing_twice_indexes_once(api, auth, world, files, db_session) -> None:
    ticket = ok(start(api, auth), 201)
    files.browser_upload(ticket["fields"]["key"], TEXT)
    ok(finish(api, auth, ticket["upload_id"]), 201)
    assert finish(api, auth, ticket["upload_id"]).status_code == 404
    assert documents(db_session, world) == 1


def test_a_late_finish_expires(api, auth, world, files, db_session) -> None:
    ticket = ok(start(api, auth), 201)
    files.browser_upload(ticket["fields"]["key"], TEXT)
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    row = db_session.get(KnowledgeUpload, uuid.UUID(ticket["upload_id"]))
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()
    assert code_of(finish(api, auth, ticket["upload_id"])) == (410, "upload_expired")
    assert files.objects == {}


# --- the clean-up sweep and isolation -----------------------------------------------------------


def test_the_sweep_removes_day_old_uploads_and_their_files(
    api, auth, world, files, db_session
) -> None:
    old = ok(start(api, auth), 201)
    fresh = ok(start(api, auth, name="other.txt"), 201)
    for ticket in (old, fresh):
        files.browser_upload(ticket["fields"]["key"], TEXT)
    tenant = world.users["alpha.admin"].tenant_id
    bind_tenant(db_session, tenant)
    row = db_session.get(KnowledgeUpload, uuid.UUID(old["upload_id"]))
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(days=2)
    db_session.flush()
    assert uploads.delete_stale_uploads(db_session, files, datetime.now(UTC), tenant_id=tenant) == 1
    assert old["fields"]["key"] not in files.objects and fresh["fields"]["key"] in files.objects


def test_another_organisation_never_sees_my_pending_uploads(
    api, auth, world, files, db_session
) -> None:
    ok(start(api, auth), 201)
    bind_tenant(db_session, world.users["beta.admin"].tenant_id)
    assert db_session.scalar(select(func.count()).select_from(KnowledgeUpload)) == 0
