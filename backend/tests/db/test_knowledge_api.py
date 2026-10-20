# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""RAG R1 - knowledge upload, ingestion and isolation through the real API and PostgreSQL.

People and tenants come from test_quotes_api.py (alpha.admin is a tenant admin, alpha.agent1 a
sales agent, beta.admin another tenant). Files go to an in-memory store.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.knowledge import api as knowledge_api
from app.modules.knowledge.models import KnowledgeChunk
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world  # noqa: F401

DOCS = "/api/v1/knowledge/documents"
TEXT = (
    b"Returns policy\n\nDamaged items may be returned within 14 days of delivery.\n\n"
    b"Delivery usually takes three to five working days.\n"
)
CARD_TEXT = b"Customer card: 4111 1111 1111 1111. Do not index this file.\n"


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


def upload(
    api: TestClient,
    auth: Headers,
    *,
    user: str = "alpha.admin",
    name: str = "returns.txt",
    data: bytes = TEXT,
    mime: str = "text/plain",
    title: str | None = None,
):
    form = {} if title is None else {"title": title}
    return api.post(
        DOCS,
        data=form,
        files={"file": (name, data, mime)},
        headers=auth(user),
    )


def run_ingest(files: MemoryFileStore, db_session, document_id: str) -> None:
    job = db_session.scalars(
        select(OutboxJob).where(
            OutboxJob.kind == knowledge_api.JOB_KIND,
            OutboxJob.payload["document_id"].astext == document_id,
        )
    ).one()
    knowledge_api.ingest_handler(files)(db_session, job)
    db_session.commit()


def test_upload_creates_one_job_and_the_worker_indexes_chunks(api, auth, world, files, db_session):
    created = ok(upload(api, auth, title="Returns"), 201)
    assert created["status"] == "processing"
    assert created["chunk_count"] == 0
    assert created["title"] == "Returns"

    run_ingest(files, db_session, created["id"])
    indexed = ok(api.get(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")))
    assert indexed["status"] == "indexed"
    assert indexed["chunk_count"] >= 1

    chunks = db_session.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == uuid.UUID(created["id"]))
    ).all()
    assert chunks and all(
        chunk.tenant_id == world.users["alpha.admin"].tenant_id for chunk in chunks
    )


def test_reingest_is_idempotent(api, auth, world, files, db_session):
    created = ok(upload(api, auth), 201)
    run_ingest(files, db_session, created["id"])
    first = ok(api.get(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")))["chunk_count"]
    run_ingest(files, db_session, created["id"])
    second = ok(api.get(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")))["chunk_count"]
    assert first == second


def test_personal_data_needs_review_and_no_chunks(api, auth, files, db_session):
    created = ok(upload(api, auth, name="card.txt", data=CARD_TEXT), 201)
    run_ingest(files, db_session, created["id"])
    document = ok(api.get(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")))
    assert document["status"] == "needs_review"
    assert document["chunk_count"] == 0
    assert document["error"] == "personal_data:card_number"


def test_whitespace_only_file_is_no_text(api, auth, files, db_session):
    created = ok(upload(api, auth, name="blank.txt", data=b"   \n\n   \n"), 201)
    run_ingest(files, db_session, created["id"])
    assert (
        ok(api.get(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")))["status"] == "no_text"
    )


def test_invalid_files_are_refused(api, auth, files):
    assert code_of(upload(api, auth, name="tool.exe", data=b"MZ\x90\x00")) == (
        415,
        "file_type_not_allowed",
    )
    assert code_of(upload(api, auth, name="empty.txt", data=b"")) == (422, "invalid_knowledge_file")
    assert code_of(upload(api, auth, name="fake.pdf", data=b"not a pdf")) == (
        415,
        "file_type_not_allowed",
    )
    assert files.objects == {}


def test_duplicate_content_is_refused(api, auth, files):
    ok(upload(api, auth), 201)
    assert code_of(upload(api, auth, name="copy.txt")) == (409, "knowledge_document_exists")


def test_tenant_isolation(api, auth, world, files):
    created = ok(upload(api, auth), 201)
    beta_list = ok(api.get(DOCS, headers=auth("beta.admin")))
    assert beta_list["total"] == 0
    assert api.get(f"{DOCS}/{created['id']}", headers=auth("beta.admin")).status_code == 404


def test_sales_agent_can_read_but_not_manage(api, auth, files):
    assert upload(api, auth, user="alpha.agent1").status_code == 403
    assert ok(api.get(DOCS, headers=auth("alpha.agent1")))["total"] == 0


def test_delete_removes_chunks_and_file(api, auth, world, files, db_session):
    created = ok(upload(api, auth), 201)
    run_ingest(files, db_session, created["id"])
    assert files.objects
    assert api.delete(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")).status_code == 204
    assert files.objects == {}
    assert api.get(f"{DOCS}/{created['id']}", headers=auth("alpha.admin")).status_code == 404
    assert (
        db_session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == uuid.UUID(created["id"]))
        ).all()
        == []
    )
