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

from app.core.auth.principal import Principal
from app.core.errors import DomainError
from app.core.storage import DOWNLOAD_LINK_LIFETIME, FileStore, object_key
from app.modules.documents import policies
from app.modules.documents.models import DERIVED_PURPOSE, Document

__all__ = [
    "DocumentRef",
    "DownloadLink",
    "can_read_document",
    "delete_derived_document",
    "document_ref",
    "store_derived_document",
    "delete_stale_uploads",
    "download_link",
    "DocumentInfo",
    "DocumentIntegrityError",
    "find_by_content",
    "find_document",
    "latest_document",
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


def _find_by_content(
    session: Session,
    tenant_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    purpose: str,
    digest: str,
) -> Document | None:
    return session.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.record_type == record_type,
            Document.record_id == record_id,
            Document.purpose == purpose,
            Document.sha256 == digest,
        )
    ).one_or_none()


def find_by_content(
    session: Session,
    tenant_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    purpose: str,
    data: bytes,
) -> DocumentInfo | None:
    """The document of this record and purpose that holds exactly these bytes, if there is one."""
    doc = _find_by_content(
        session, tenant_id, record_type, record_id, purpose, hashlib.sha256(data).hexdigest()
    )
    return _info(doc) if doc else None


def find_document(
    session: Session, tenant_id: uuid.UUID, record_type: str, record_id: uuid.UUID, purpose: str
) -> DocumentInfo | None:
    doc = _find(session, tenant_id, record_type, record_id, purpose)
    return _info(doc) if doc else None


def latest_document(
    session: Session, tenant_id: uuid.UUID, record_type: str, record_id: uuid.UUID, purpose: str
) -> DocumentInfo | None:
    """The newest document of this record and purpose (for purposes that can have several)."""
    doc = session.scalars(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.record_type == record_type,
            Document.record_id == record_id,
            Document.purpose == purpose,
        )
        .order_by(Document.created_at.desc(), Document.id)
        .limit(1)
    ).one_or_none()
    return _info(doc) if doc else None


# The purposes whose files are stored once per distinct content, and the partial unique index each
# one conflicts on. Fixed text, never built from input.
_BY_CONTENT_PURPOSES = ("quote_deck", "quote_deck_pptx")
_CONFLICT_WHERE = {
    "quote_pdf": text("purpose = 'quote_pdf'"),
    "quote_deck": text("purpose = 'quote_deck'"),
    "quote_deck_pptx": text("purpose = 'quote_deck_pptx'"),
}


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
    unique_by_content: bool = False,
) -> DocumentInfo:
    """Store a generated file once per record and purpose; later calls return the first one.

    With ``unique_by_content`` (proposal decks) a record can have several files of the purpose, one
    per distinct content: the same bytes are stored once, new bytes become a new document.

    Safe to call twice at the same time (API download and worker): the bytes are uploaded under
    a fresh key, and the database's unique index decides which row wins; the loser's upload is
    removed again. Runs in the caller's transaction.
    """
    if unique_by_content and purpose not in _BY_CONTENT_PURPOSES:
        raise ValueError(f"{purpose!r} documents are not stored by content")
    digest = hashlib.sha256(data).hexdigest()
    if unique_by_content:
        found = _find_by_content(session, tenant_id, record_type, record_id, purpose, digest)
        if found is not None:
            return _info(found)
    else:
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
            sha256=digest,
            storage_key=key,
            customer_visible=customer_visible,
            created_by_user_id=created_by_user_id,
            group_id=document_id,
            version_no=1,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "record_type", "record_id", "sha256"]
            if unique_by_content
            else ["tenant_id", "record_type", "record_id", "purpose"],
            index_where=_CONFLICT_WHERE[purpose if unique_by_content else "quote_pdf"],
        )
        .returning(Document.id)
    )
    if inserted is None:  # someone else stored it first
        store.delete(key)
    doc = (
        _find_by_content(session, tenant_id, record_type, record_id, purpose, digest)
        if unique_by_content
        else _find(session, tenant_id, record_type, record_id, purpose)
    )
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


# --- adjusted copies of photos (ADR 0039) ----------------------------------------------------


@dataclass(frozen=True)
class DocumentRef:
    """What another module needs to know about an uploaded document (an attachment)."""

    id: uuid.UUID
    record_type: str
    record_id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    customer_visible: bool


def document_ref(
    session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentRef | None:
    """An uploaded attachment of this tenant (not a generated file, not a derived copy)."""
    doc = session.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.id == document_id,
            Document.purpose == "attachment",
        )
    ).one_or_none()
    if doc is None:
        return None
    return DocumentRef(
        doc.id,
        doc.record_type,
        doc.record_id,
        doc.file_name,
        doc.content_type,
        doc.size_bytes,
        doc.customer_visible,
    )


def can_read_document(session: Session, principal: Principal, ref: DocumentRef) -> bool:
    """Whoever may see the record the document belongs to (the documents module's own rule)."""
    return policies.record_visible(session, principal, ref.record_type, ref.record_id)


def store_derived_document(
    session: Session,
    store: FileStore,
    *,
    tenant_id: uuid.UUID,
    original: DocumentRef,
    file_name: str,
    content_type: str,
    data: bytes,
    created_by_user_id: uuid.UUID | None,
) -> DocumentInfo:
    """Store an adjusted copy next to its original: same record, same customer visibility, its own
    row that is deleted with the original. Never listed as an ordinary document."""
    document_id = uuid.uuid4()
    key = object_key(tenant_id, f"{original.record_type}s", original.record_id, document_id)
    store.put(key, data, content_type, download_name=file_name)
    doc = Document(
        id=document_id,
        tenant_id=tenant_id,
        record_type=original.record_type,
        record_id=original.record_id,
        purpose=DERIVED_PURPOSE,
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        customer_visible=original.customer_visible,
        created_by_user_id=created_by_user_id,
        group_id=document_id,
        version_no=1,
        derived_from_id=original.id,
    )
    session.add(doc)
    session.flush()
    return _info(doc)


def delete_derived_document(
    session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> str | None:
    """Delete one adjusted copy's row; returns its file key for the caller to remove after the
    commit (a failed commit must not lose the file). None when there is no such copy."""
    doc = session.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.id == document_id,
            Document.purpose == DERIVED_PURPOSE,
        )
    ).one_or_none()
    if doc is None:
        return None
    key = doc.storage_key
    session.delete(doc)
    session.flush()
    return key
