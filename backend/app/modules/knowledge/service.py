"""Knowledge ingestion rules (RAG R1). Services never commit; the router/worker does.

Uploading stores the bytes, creates the document row and queues the ingestion job in ONE
transaction. The worker then extracts text, checks for personal data, chunks and replaces the
document's chunks.
"""

import hashlib
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.outbox import enqueue
from app.core.storage import FileStore, StoredFileMissingError, object_key
from app.modules.knowledge import chunking, extraction, pii, repository, rules
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument

JOB_KIND = "knowledge.ingest"
CHUNKING_VERSION = chunking.CHUNKING_VERSION


class KnowledgeDocumentNotFoundError(NotFoundError):
    code = "knowledge_document_not_found"

    def __init__(self) -> None:
        super().__init__("The knowledge document doesn't exist or you don't have access to it.")


class FileTooLargeError(DomainError):
    status_code = 413
    code = "file_too_large"


class FileTypeNotAllowedError(DomainError):
    status_code = 415
    code = "file_type_not_allowed"


class InvalidKnowledgeFileError(DomainError):
    status_code = 422
    code = "invalid_knowledge_file"


class DuplicateKnowledgeDocumentError(ConflictError):
    code = "knowledge_document_exists"

    def __init__(self) -> None:
        super().__init__("This file has already been added to the knowledge base.")


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise KnowledgeDocumentNotFoundError()
    return principal.tenant_id


def create_document(
    session: Session,
    principal: Principal,
    store: FileStore,
    *,
    title: str,
    file_name: str,
    content_type: str,
    data: bytes,
    max_bytes: int,
) -> KnowledgeDocument:
    tenant_id = _tenant(principal)
    if not data:
        raise InvalidKnowledgeFileError("The file is empty.")
    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit."
        )
    kind = rules.detect(file_name, data[:4096])
    if kind is None:
        raise FileTypeNotAllowedError(f"Only {rules.ALLOWED_LABEL} files can be indexed.")

    sha256 = hashlib.sha256(data).hexdigest()
    existing = session.scalar(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.sha256 == sha256
        )
    )
    if existing is not None:
        raise DuplicateKnowledgeDocumentError()

    document_id = uuid.uuid4()
    storage_key = object_key(tenant_id, "knowledge", document_id, document_id)
    store.put(storage_key, data, content_type or kind.content_type)
    document = KnowledgeDocument(
        id=document_id,
        tenant_id=tenant_id,
        title=title.strip()[:200] or rules.title_from(file_name),
        file_name=file_name,
        content_type=kind.content_type,
        size_bytes=len(data),
        sha256=sha256,
        storage_key=storage_key,
        status="processing",
        page_count=0,
        created_by_user_id=principal.user_id,
    )
    session.add(document)
    enqueue(
        session,
        tenant_id=tenant_id,
        kind=JOB_KIND,
        payload={"document_id": str(document_id)},
    )
    record_audit(
        session,
        principal,
        action="knowledge.document_uploaded",
        entity_type="knowledge_document",
        entity_id=document_id,
        changes={"title": document.title, "file_name": file_name, "size_bytes": len(data)},
    )
    return document


def ingest_document(
    session: Session, store: FileStore, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """Worker job body: turn one document's bytes into chunks, atomically per version."""
    document = repository.get_document_for_worker(session, tenant_id, document_id)
    if document is None:
        return  # deleted before the job ran - nothing to do, and that is not an error

    try:
        data = store.get(document.storage_key)
    except StoredFileMissingError:
        document.status = "failed"
        document.error = "file_missing"
        return

    if len(data) != document.size_bytes or hashlib.sha256(data).hexdigest() != document.sha256:
        document.status = "failed"
        document.error = "file_integrity"
        return

    try:
        sections = extraction.extract_sections(document.file_name, data)
    except extraction.ExtractionError:
        document.status = "failed"
        document.error = "extraction_failed"
        return

    if not sections or not any(section.blocks for section in sections):
        document.status = "no_text"
        document.error = "no_text"
        return

    findings = pii.scan_sections(sections)
    if findings:
        document.status = "needs_review"
        document.error = "personal_data:" + ",".join(findings)
        return

    chunks = chunking.chunk_sections(sections)
    repository.replace_chunks(session, tenant_id, document_id, chunks)
    document.status = "indexed"
    document.error = None
    document.page_count = extraction.page_count(sections)


def list_documents(
    session: Session,
    principal: Principal,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[KnowledgeDocument], int]:
    return repository.list_documents(session, principal, status=status, limit=limit, offset=offset)


def get_document(
    session: Session, principal: Principal, document_id: uuid.UUID
) -> KnowledgeDocument:
    document = repository.get_document(session, principal, document_id)
    if document is None:
        raise KnowledgeDocumentNotFoundError()
    return document


def delete_document(
    session: Session, principal: Principal, store: FileStore, document_id: uuid.UUID
) -> None:
    document = get_document(session, principal, document_id)
    session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.tenant_id == document.tenant_id,
            KnowledgeChunk.document_id == document.id,
        )
    )
    store.delete(document.storage_key)
    session.delete(document)
    record_audit(
        session,
        principal,
        action="knowledge.document_deleted",
        entity_type="knowledge_document",
        entity_id=document.id,
        changes={"file_name": document.file_name},
    )
