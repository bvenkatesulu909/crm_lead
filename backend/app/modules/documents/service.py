"""Document rules (Phase 10). Functions here never commit: the router commits once.

- A document belongs to an account or a deal. Whoever may see that record may see and download
  its documents (policies.py); uploading needs document:write, deleting document:delete.
- Uploading a file with the same name to the same record adds a new VERSION; older versions
  stay available to staff. Customers see only the newest version, and only if it is marked
  "visible to the customer" (account documents only).
- Bytes go to the S3 file store under tenant/{tenant}/{record type}s/{record}/{document};
  keys are built only from server-side IDs.
"""

import hashlib
import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.storage import FileStore, object_key
from app.modules.documents import api as documents_api
from app.modules.documents import repository, rules
from app.modules.documents.models import Document
from app.modules.documents.policies import record_visible
from app.modules.documents.schemas import DocumentRead, PortalDocumentRead
from app.modules.identity import api as identity_api

logger = logging.getLogger(__name__)
ENTITY = "document"


class DocumentNotFoundError(NotFoundError):
    code = "document_not_found"

    def __init__(self) -> None:
        super().__init__("The document doesn't exist or you don't have access to it.")


class RecordNotFoundError(NotFoundError):
    code = "record_not_found"

    def __init__(self) -> None:
        super().__init__("The record doesn't exist or you don't have access to it.")


class FileTooLargeError(DomainError):
    status_code = 413
    code = "file_too_large"


class FileTypeNotAllowedError(DomainError):
    status_code = 415
    code = "file_type_not_allowed"


class InvalidDocumentError(DomainError):
    status_code = 422
    code = "invalid_document"


class UploadConflictError(ConflictError):
    code = "upload_conflict"


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise RecordNotFoundError()
    return principal.tenant_id


def _check_record(
    session: Session, principal: Principal, record_type: str, record_id: uuid.UUID
) -> uuid.UUID:
    tenant_id = _tenant(principal)
    if not record_visible(session, principal, record_type, record_id):
        raise RecordNotFoundError()
    return tenant_id


def _load(session: Session, principal: Principal, document_id: uuid.UUID) -> Document:
    """A document of a record the caller may see - otherwise 404 (never revealing it exists)."""
    doc = repository.get(session, _tenant(principal), document_id)
    if doc is None or not record_visible(session, principal, doc.record_type, doc.record_id):
        raise DocumentNotFoundError()
    return doc


def _read_models(session: Session, rows: list[tuple[Document, int]]) -> list[DocumentRead]:
    if not rows:
        return []
    people = identity_api.people_by_id(
        session,
        rows[0][0].tenant_id,
        {d.created_by_user_id for d, _ in rows if d.created_by_user_id},
    )
    return [
        DocumentRead.model_validate(d).model_copy(
            update={
                "versions": count,
                "created_by_name": people.get(d.created_by_user_id, ("Former user", ""))[0]
                if d.created_by_user_id
                else None,
            }
        )
        for d, count in rows
    ]


def list_documents(
    session: Session, principal: Principal, record_type: str, record_id: uuid.UUID
) -> list[DocumentRead]:
    tenant_id = _check_record(session, principal, record_type, record_id)
    return _read_models(
        session, repository.latest_for_record(session, tenant_id, record_type, record_id)
    )


def upload(
    session: Session,
    principal: Principal,
    store: FileStore,
    *,
    record_type: str,
    record_id: uuid.UUID,
    file_name: str | None,
    data: bytes,
    max_bytes: int,
    customer_visible: bool,
    description: str | None,
) -> DocumentRead:
    tenant_id = _check_record(session, principal, record_type, record_id)
    if customer_visible and record_type != "account":
        raise InvalidDocumentError("Only account documents can be shown to the customer.")
    if not data:
        raise InvalidDocumentError("The file is empty.")
    if len(data) > max_bytes:
        raise FileTooLargeError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    name = rules.clean_file_name(file_name)
    kind = rules.detect(name, data[:4096])
    if kind is None:
        raise FileTypeNotAllowedError(
            f"This file type isn't allowed. Allowed: {rules.ALLOWED_LABEL}."
        )
    existing = repository.group_by_name(session, tenant_id, record_type, record_id, name)
    document_id = uuid.uuid4()
    group_id, version_no = (existing[0], existing[1] + 1) if existing else (document_id, 1)
    key = object_key(tenant_id, f"{record_type}s", record_id, document_id)
    store.put(key, data, kind.content_type)
    doc = Document(
        id=document_id,
        tenant_id=tenant_id,
        record_type=record_type,
        record_id=record_id,
        purpose=repository.ATTACHMENT,
        file_name=name,
        content_type=kind.content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        customer_visible=customer_visible,
        created_by_user_id=principal.user_id,
        group_id=group_id,
        version_no=version_no,
        description=description,
    )
    session.add(doc)
    try:
        session.flush()
    except IntegrityError as exc:  # two uploads of the same name at the same moment
        store.delete(key)
        raise UploadConflictError(
            "Someone uploaded this file at the same time. Try again."
        ) from exc
    record_audit(
        session,
        principal,
        action="document.uploaded",
        entity_type=ENTITY,
        entity_id=doc.id,
        changes={
            "record": f"{record_type}:{record_id}",
            "file_name": name,
            "version": version_no,
            "customer_visible": customer_visible,
        },
    )
    session.refresh(doc)
    return _read_models(session, [(doc, version_no)])[0]


def versions(session: Session, principal: Principal, document_id: uuid.UUID) -> list[DocumentRead]:
    doc = _load(session, principal, document_id)
    rows = repository.versions(session, doc.tenant_id, doc.group_id)
    return _read_models(session, [(d, len(rows)) for d in rows])


def download(
    session: Session, principal: Principal, store: FileStore, document_id: uuid.UUID
) -> tuple[documents_api.DocumentInfo, bytes]:
    doc = _load(session, principal, document_id)
    return documents_api.read_document(session, store, doc.tenant_id, doc.id)


def delete_document(session: Session, principal: Principal, document_id: uuid.UUID) -> list[str]:
    """Deletes the document with ALL its versions. Returns the file keys, which the router
    removes from the store after the database commit (a failed commit must not lose files)."""
    doc = _load(session, principal, document_id)
    rows = repository.versions(session, doc.tenant_id, doc.group_id)
    keys = [d.storage_key for d in rows]
    session.execute(
        delete(Document).where(
            Document.tenant_id == doc.tenant_id, Document.group_id == doc.group_id
        )
    )
    record_audit(
        session,
        principal,
        action="document.deleted",
        entity_type=ENTITY,
        entity_id=doc.group_id,
        changes={
            "record": f"{doc.record_type}:{doc.record_id}",
            "file_name": doc.file_name,
            "versions": len(rows),
        },
    )
    return keys


def remove_files(store: FileStore, keys: list[str]) -> None:
    for key in keys:
        try:
            store.delete(key)
        except Exception:  # noqa: BLE001 - an orphaned file is harmless; the row is gone
            logger.warning("could not remove a deleted document's file")


# --- customer portal ------------------------------------------------------------------------


def _portal_latest(session: Session, principal: Principal, account_id: uuid.UUID) -> list[Document]:
    tenant_id = _check_record(session, principal, "account", account_id)
    return [
        d
        for d, _ in repository.latest_for_record(session, tenant_id, "account", account_id)
        if d.customer_visible
    ]


def portal_list(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> list[PortalDocumentRead]:
    return [
        PortalDocumentRead.model_validate(d, from_attributes=True)
        for d in _portal_latest(session, principal, account_id)
    ]


def portal_download(
    session: Session, principal: Principal, store: FileStore, document_id: uuid.UUID
) -> tuple[documents_api.DocumentInfo, bytes]:
    """Customers get only the newest, customer-visible version of their own accounts' files."""
    doc = repository.get(session, _tenant(principal), document_id)
    if doc is None or doc.record_type != "account":
        raise DocumentNotFoundError()
    if doc.id not in {d.id for d in _portal_latest(session, principal, doc.record_id)}:
        raise DocumentNotFoundError()
    return documents_api.read_document(session, store, doc.tenant_id, doc.id)
