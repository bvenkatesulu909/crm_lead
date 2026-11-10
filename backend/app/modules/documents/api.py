"""Public interface of the documents module (ADR 0005). Other modules import only from here.

Documents belong to a record of another module (e.g. a quote). Authorization stays with that
module: it checks that the caller may see its record, then calls these functions. Everything
here is scoped by ``tenant_id``, which callers take from the principal or the job - never from
the request.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.storage import DOWNLOAD_LINK_LIFETIME, FileStore, object_key
from app.modules.documents.models import Document

__all__ = [
    "DownloadLink",
    "delete_stale_uploads",
    "download_link",
    "DocumentInfo",
    "DocumentIntegrityError",
    "find_document",
    "read_document",
    "store_generated_document",
]


class DocumentIntegrityError(DomainError):
    """The stored bytes don't match the checksum saved when the document was created."""

    status_code = 500
    code = "document_integrity"


@dataclass(frozen=True)
class DocumentInfo:
    id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    customer_visible: bool
    created_at: datetime


def _info(doc: Document) -> DocumentInfo:
    return DocumentInfo(
        doc.id,
        doc.file_name,
        doc.content_type,
        doc.size_bytes,
        doc.sha256,
        doc.customer_visible,
        doc.created_at,
    )


def _find(
    session: Session, tenant_id: uuid.UUID, record_type: str, record_id: uuid.UUID, purpose: str
) -> Document | None:
    return session.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.record_type == record_type,
            Document.record_id == record_id,
            Document.purpose == purpose,
        )
    ).one_or_none()


def find_document(
    session: Session, tenant_id: uuid.UUID, record_type: str, record_id: uuid.UUID, purpose: str
) -> DocumentInfo | None:
    doc = _find(session, tenant_id, record_type, record_id, purpose)
    return _info(doc) if doc else None


def store_generated_document(
    session: Session,
    store: FileStore,
    *,
    tenant_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    purpose: str,
    file_name: str,
    content_type: str,
    data: bytes,
    customer_visible: bool,
    created_by_user_id: uuid.UUID | None,
) -> DocumentInfo:
    """Store a generated file once per record and purpose; later calls return the first one.

    Safe to call twice at the same time (API download and worker): the bytes are uploaded under
    a fresh key, and the database's unique index decides which row wins; the loser's upload is
    removed again. Runs in the caller's transaction.
    """
    existing = _find(session, tenant_id, record_type, record_id, purpose)
    if existing is not None:
        return _info(existing)
    document_id = uuid.uuid4()
    key = object_key(tenant_id, f"{record_type}s", record_id, document_id)
    store.put(key, data, content_type, download_name=file_name)
    inserted = session.scalar(
        insert(Document)
        .values(
            id=document_id,
            tenant_id=tenant_id,
            record_type=record_type,
            record_id=record_id,
            purpose=purpose,
            file_name=file_name,
            content_type=content_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            storage_key=key,
            customer_visible=customer_visible,
            created_by_user_id=created_by_user_id,
            group_id=document_id,
            version_no=1,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "record_type", "record_id", "purpose"],
            index_where=text("purpose = 'quote_pdf'"),
        )
        .returning(Document.id)
    )
    if inserted is None:  # someone else stored it first
        store.delete(key)
    doc = _find(session, tenant_id, record_type, record_id, purpose)
    assert doc is not None  # noqa: S101 - just inserted or found by the unique index
    return _info(doc)


def read_document(
    session: Session, store: FileStore, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[DocumentInfo, bytes]:
    """Bytes of a document of this tenant, checked against the saved checksum."""
    doc = session.scalars(
        select(Document).where(Document.tenant_id == tenant_id, Document.id == document_id)
    ).one()
    data = store.get(doc.storage_key)
    if len(data) != doc.size_bytes or hashlib.sha256(data).hexdigest() != doc.sha256:
        raise DocumentIntegrityError("The stored file is damaged. Please contact support.")
    return _info(doc), data


@dataclass(frozen=True)
class DownloadLink:
    """A 60-second signed link to one stored file (ADR 0025): the browser fetches it straight
    from the file store, so large files never pass through the web app's host."""

    url: str
    file_name: str
    expires_at: datetime


def download_link(
    session: Session, store: FileStore, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> DownloadLink:
    """A link for a document of this tenant. Callers have already checked that the person may
    read it. The stored object's size must match the record: the bytes are not read here (that
    is the point), so the full SHA-256 check stays with ``read_document``; only the API holds the
    store's write keys, so the size check catches a missing or truncated file."""
    doc = session.scalars(
        select(Document).where(Document.tenant_id == tenant_id, Document.id == document_id)
    ).one()
    if store.stat(doc.storage_key).size != doc.size_bytes:
        raise DocumentIntegrityError("The stored file is damaged. Please contact support.")
    url = store.signed_download(doc.storage_key, file_name=doc.file_name)
    return DownloadLink(url, doc.file_name, datetime.now(UTC) + DOWNLOAD_LINK_LIFETIME)


def delete_stale_uploads(
    session: Session, store: FileStore | None, now: datetime, *, tenant_id: uuid.UUID
) -> int:
    """The worker's sweep for direct uploads a day old (ADR 0025)."""
    from app.modules.documents import uploads  # the service imports this module: import late

    return uploads.delete_stale_uploads(session, store, now, tenant_id=tenant_id)
