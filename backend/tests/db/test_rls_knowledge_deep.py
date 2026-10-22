"""Deep audit of the CURRENT RLS boundary (knowledge tables only)."""

import hashlib
import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant, clear_tenant
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from tests.db.test_quotes_api import world  # noqa: F401


def _doc(tenant_id: uuid.UUID, title: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        title=title,
        file_name=f"{title}.txt",
        content_type="text/plain",
        size_bytes=1,
        sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        storage_key=f"k/{uuid.uuid4()}",
        status="indexed",
        page_count=0,
        group_id=uuid.uuid4(),
        version=1,
        visibility="internal",
    )


@pytest.fixture
def two_tenants(db_session: Session, world):  # noqa: F811
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)
    alpha_doc = _doc(alpha, "Alpha doc")
    db_session.add(alpha_doc)
    db_session.flush()
    bind_tenant(db_session, beta)
    beta_doc = _doc(beta, "Beta doc")
    db_session.add(beta_doc)
    db_session.flush()
    return alpha, beta, alpha_doc, beta_doc


def test_select_is_scoped_and_missing_context_is_fail_closed(db_session, two_tenants):
    alpha, beta, alpha_doc, beta_doc = two_tenants
    bind_tenant(db_session, alpha)
    ids = set(db_session.scalars(select(KnowledgeDocument.id)).all())
    assert ids == {alpha_doc.id}
    bind_tenant(db_session, beta)
    ids = set(db_session.scalars(select(KnowledgeDocument.id)).all())
    assert ids == {beta_doc.id}
    clear_tenant(db_session)
    assert db_session.scalars(select(KnowledgeDocument.id)).all() == []


def test_insert_with_another_tenants_id_is_rejected(db_session, two_tenants):
    alpha, beta, _alpha_doc, _beta_doc = two_tenants
    bind_tenant(db_session, alpha)
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.add(_doc(beta, "Smuggled doc"))
        db_session.flush()


def test_insert_without_tenant_context_is_rejected(db_session, two_tenants):
    alpha, _beta, _alpha_doc, _beta_doc = two_tenants
    clear_tenant(db_session)
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.add(_doc(alpha, "No context doc"))
        db_session.flush()


def test_update_and_delete_cannot_cross_tenants(db_session, two_tenants):
    alpha, _beta, _alpha_doc, beta_doc = two_tenants
    bind_tenant(db_session, alpha)
    changed = db_session.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == beta_doc.id)
        .values(title="hijacked")
    ).rowcount
    removed = db_session.execute(
        delete(KnowledgeDocument).where(KnowledgeDocument.id == beta_doc.id)
    ).rowcount
    assert changed == 0
    assert removed == 0
    bind_tenant(db_session, _beta)
    assert db_session.get(KnowledgeDocument, beta_doc.id).title == "Beta doc"


def test_cross_tenant_chunk_fk_is_rejected(db_session, two_tenants, app_engine):
    alpha, _beta, _alpha_doc, beta_doc = two_tenants
    bind_tenant(db_session, alpha)
    chunk = KnowledgeChunk(
        tenant_id=alpha,
        document_id=beta_doc.id,
        chunk_no=1,
        text="leak",
        blocks=["leak"],
        heading_path="",
        char_count=4,
        chunking_version="1",
        embedding_model="m",
        visibility="internal",
    )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.add(chunk)
        db_session.flush()


def test_tenant_setting_is_transaction_local(app_engine, two_tenants):
    alpha, _beta, _alpha_doc, _beta_doc = two_tenants
    with app_engine.connect() as connection:
        connection.execute(
            text("select set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(alpha)},
        )
        assert connection.scalar(text("select current_setting('app.tenant_id', true)")) == str(
            alpha
        )
        connection.commit()
        # set_config(..., true) is transaction-local: a pooled connection cannot keep it.
        assert connection.scalar(text("select current_setting('app.tenant_id', true)")) in (
            None,
            "",
        )


def test_app_role_cannot_disable_row_security(db_session):
    assert db_session.scalar(text("select current_user")) == "crm_app"
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("set local row_security = off"))
        db_session.execute(text("select count(*) from kb_documents")).scalar()
