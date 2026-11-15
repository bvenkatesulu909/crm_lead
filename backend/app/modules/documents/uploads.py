"""Direct uploads (ADR 0025): the file goes from the browser straight to the file store, so large
files never pass through the web app's host (Netlify refuses requests of 6 MB or more).

    start  - the same checks as a normal upload that can be made before the bytes arrive
             (permission, a record the person may see, account-only customer visibility, size,
             a type allowed by name), a per-person hourly limit, then ONE pending row and a
             five-minute signed link for ``pending/{tenant}/{upload}``. The store itself refuses
             another key, another type or a bigger body.
    finish - the row is locked and must be this person's, still pending and not too old; the
             stored size is checked; the bytes are read back once and handed to ``service.upload``,
             so every content check, version, audit entry and event is exactly a normal upload's;
             then the pending file is deleted.

Everything ``finish`` needs (record, name, visibility, description) comes from the row, never from
the browser. Functions here never commit: the router commits once.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.storage import FileStore, StoredFileMissingError, pending_key
from app.modules.documents import rules, service
from app.modules.documents.models import DocumentUpload
from app.modules.documents.schemas import DocumentRead, UploadStart, UploadTicket

logger = logging.getLogger(__name__)
STALE_AFTER = timedelta(days=1)


class UploadNotFoundError(NotFoundError):
    code = "upload_not_found"

    def __init__(self) -> None:
        super().__init__("The upload doesn't exist, is not yours, or was already finished.")


class UploadNotReceivedError(ConflictError):
    code = "upload_not_received"

    def __init__(self) -> None:
        super().__init__("The file has not arrived in the file store yet. Send it, then finish.")


class UploadExpiredError(DomainError):
    status_code = 410
    code = "upload_expired"

    def __init__(self) -> None:
        super().__init__("This upload took too long. Start it again.")


class UploadLimitError(DomainError):
    status_code = 429
    code = "upload_limit_reached"

    def __init__(self) -> None:
        super().__init__("Too many uploads started in the last hour. Try again later.")


def start_upload(
    session: Session,
    principal: Principal,
    store: FileStore,
    body: UploadStart,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> UploadTicket:
    when = now or datetime.now(UTC)
    tenant_id = service._check_record(  # noqa: SLF001 - the module's own rule, shared on purpose
        session, principal, body.record_type, body.record_id
    )
    if principal.user_id is None:
        raise service.RecordNotFoundError()
    if body.customer_visible and body.record_type != "account":
        raise service.InvalidDocumentError("Only account documents can be shown to the customer.")
    max_bytes = settings.files_max_bytes
    if body.size_bytes > max_bytes:
        raise service.FileTooLargeError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    name = rules.clean_file_name(body.file_name)
    kind = rules.ALLOWED.get(rules.extension(name))
    if kind is None:
        raise service.FileTypeNotAllowedError(
            f"This file type isn't allowed. Allowed: {rules.ALLOWED_LABEL}."
        )
    started = session.scalar(
        select(func.count())
        .select_from(DocumentUpload)
        .where(
            DocumentUpload.tenant_id == tenant_id,
            DocumentUpload.created_by_user_id == principal.user_id,
            DocumentUpload.created_at >= when - timedelta(hours=1),
        )
    )
    if int(started or 0) >= settings.files_uploads_per_user_hour:
        raise UploadLimitError()
    row = DocumentUpload(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_by_user_id=principal.user_id,
        record_type=body.record_type,
        record_id=body.record_id,
        file_name=name,
        content_type=kind.content_type,
        declared_size=body.size_bytes,
        customer_visible=body.customer_visible,
        description=body.description or None,
        created_at=when,
    )
    session.add(row)
    session.flush()
    signed = store.signed_upload(
        pending_key(tenant_id, row.id), content_type=kind.content_type, max_bytes=body.size_bytes
    )
    return UploadTicket(
        upload_id=row.id,
        url=signed.url,
        fields=signed.fields,
        expires_at=signed.expires_at,
        max_bytes=body.size_bytes,
    )


def finish_upload(
    session: Session,
    principal: Principal,
    store: FileStore,
    upload_id: uuid.UUID,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> DocumentRead:
    when = now or datetime.now(UTC)
    if principal.tenant_id is None or principal.user_id is None:
        raise UploadNotFoundError()
    row = session.scalar(
        select(DocumentUpload)
        .where(
            DocumentUpload.tenant_id == principal.tenant_id,
            DocumentUpload.id == upload_id,
            DocumentUpload.created_by_user_id == principal.user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.status != "pending":
        raise UploadNotFoundError()
    key = pending_key(row.tenant_id, row.id)
    if row.created_at < when - timedelta(minutes=settings.files_upload_finish_minutes):
        row.status = "expired"
        session.flush()
        _forget(store, key)
        raise UploadExpiredError()
    try:
        found = store.stat(key)
    except StoredFileMissingError:
        raise UploadNotReceivedError() from None
    if found.size > row.declared_size or found.size > settings.files_max_bytes:
        # The store refuses this for a POST policy; a store that only signs PUT would not.
        _forget(store, key)
        raise service.FileTooLargeError("The file is larger than the size that was announced.")
    data = store.get(key)
    try:
        result = service.upload(
            session,
            principal,
            store,
            record_type=row.record_type,
            record_id=row.record_id,
            file_name=row.file_name,
            data=data,
            max_bytes=settings.files_max_bytes,
            customer_visible=row.customer_visible,
            description=row.description,
        )
    except DomainError:
        _forget(store, key)  # a refused file is not kept, not even as pending
        raise
    row.status = "finished"
    row.document_id = result.id
    row.finished_at = when
    session.flush()
    _forget(store, key)
    return result


def _forget(store: FileStore, key: str) -> None:
    try:
        store.delete(key)
    except Exception:  # noqa: BLE001 - the worker's sweep removes what is left
        logger.warning("could not remove a pending upload's file")


def delete_stale_uploads(
    session: Session, store: FileStore | None, now: datetime, *, tenant_id: uuid.UUID
) -> int:
    """Uploads started more than a day ago, finished or not: the row goes, and any pending file
    left behind (a file sent but never finished) is removed from the store."""
    stale = list(
        session.scalars(
            select(DocumentUpload.id).where(
                DocumentUpload.tenant_id == tenant_id,
                DocumentUpload.created_at < now - STALE_AFTER,
            )
        )
    )
    if not stale:
        return 0
    if store is not None:
        for upload_id in stale:
            _forget(store, pending_key(tenant_id, upload_id))
    session.execute(
        delete(DocumentUpload).where(
            DocumentUpload.tenant_id == tenant_id, DocumentUpload.id.in_(stale)
        )
    )
    return len(stale)
