"""R6.2/R6.3 freshness, retention and erasure."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import bind_tenant
from app.modules.knowledge import freshness
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument, RagQuery
from tests.db.test_quotes_api import world  # noqa: F401


def _doc(tenant_id, **values):
    data = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "title": "Doc",
        "file_name": "doc.txt",
        "content_type": "text/plain",
        "size_bytes": 1,
        "sha256": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "storage_key": f"k/{uuid.uuid4()}",
        "status": "indexed",
        "page_count": 0,
        "group_id": uuid.uuid4(),
        "version": 1,
        "visibility": "internal",
    }
    data.update(values)
    return KnowledgeDocument(**data)


def _chunk(tenant_id, document_id, model="m"):
    return KnowledgeChunk(
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_no=1,
        text="x",
        blocks=["x"],
        heading_path="",
        char_count=1,
        chunking_version="1",
        embedding_model=model,
        visibility="internal",
    )


def test_maintenance_reports_freshness_and_deletes_old_queries(db_session, world):  # noqa: F811
    tenant = world.users["alpha.admin"].tenant_id
    bind_tenant(db_session, tenant)
    now = datetime.now(UTC)
    missing = _doc(tenant)
    archived = _doc(tenant, is_archived=True, archived_at=now)
    old_model_doc = _doc(tenant)
    stuck = _doc(tenant, status="processing", created_at=now - timedelta(hours=2))
    db_session.add_all([missing, archived, old_model_doc, stuck])
    db_session.flush()
    db_session.add_all(
        [
            _chunk(tenant, archived.id),
            _chunk(tenant, old_model_doc.id, model="old-model"),
        ]
    )
    old_query = RagQuery(
        tenant_id=tenant,
        surface="staff_answer",
        question="old",
        sources=[],
        created_at=now - timedelta(days=91),
    )
    new_query = RagQuery(
        tenant_id=tenant, surface="staff_answer", question="new", sources=[], created_at=now
    )
    db_session.add_all([old_query, new_query])
    db_session.flush()

    report = freshness.maintenance_for_tenant(db_session, tenant, embedding_model="m", now=now)

    assert report == {
        "published_without_chunks": 1,
        "chunks_of_archived_documents": 1,
        "chunks_from_old_embedding_model": 1,
        "documents_stuck_processing": 1,
        "rag_queries_deleted": 1,
    }
    assert db_session.scalars(select(RagQuery)).all() == [new_query]


def test_erasure_removes_the_persons_questions(db_session, world):  # noqa: F811
    tenant = world.users["alpha.customer"].tenant_id
    user = world.users["alpha.customer"]
    bind_tenant(db_session, tenant)
    db_session.add_all(
        [
            RagQuery(
                tenant_id=tenant,
                user_id=user.id,
                surface="portal_answer",
                question="mine",
                sources=[],
            ),
            RagQuery(
                tenant_id=tenant,
                user_id=world.users["alpha.customer2"].id,
                surface="portal_answer",
                question="other",
                sources=[],
            ),
        ]
    )
    db_session.flush()

    assert freshness.erase_user_queries(db_session, tenant, user.id) == 1
    remaining = db_session.scalars(select(RagQuery)).all()
    assert [row.question for row in remaining] == ["other"]