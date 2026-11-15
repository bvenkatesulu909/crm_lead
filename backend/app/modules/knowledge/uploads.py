"""Direct uploads of knowledge documents (ADR 0025, DU3b): the file goes from the browser straight
to the file store, so files above the web host's limit (Netlify: 6 MB) can be indexed.

    start  - the checks a normal knowledge upload makes that need no bytes (knowledge:manage,
             visibility, an internal document is never linked to one account, the account must be
             readable, the document to replace must exist and not be archived, size, a type
             allowed by name), a per-person hourly limit, then ONE pending row and a five-minute
             signed link for ``pending/{tenant}/{upload}``.
    finish - the row is locked and must be this person's, still pending and not too old; the
             stored size is re-checked; the bytes are read back once and handed to the normal
             ``service.create_document``, so the content check, duplicate detection, versions,
             the indexing job and the audit entry are exactly a normal upload's; then the pending
             file is deleted (also when the file is refused).

Everything ``finish`` uses comes from the row, never from the browser. Nothing here commits.
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
from app.modules.knowledge import rules, service
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeUpload
from app.modules.knowledge.schemas import KnowledgeUploadStart, KnowledgeUploadTicket

logger = logging.getLogger(__name__)
STALE_AFTER = timedelta(days=1)


class KnowledgeUploadNotFoundError(NotFoundError):
    code = "upload_not_found"

    def __init__(self) -> None:
        super().__init__("The upload doesn't exist, is not yours, or was already finished.")


class KnowledgeUploadNotReceivedError(ConflictError):
    code = "upload_not_received"

    def __init__(self) -> None:
        super().__init__("The file has not arrived in the file store yet. Send it, then finish.")


class KnowledgeUploadExpiredError(DomainError):
    status_code = 410
    code = "upload_expired"

    def __init__(self) -> None:
        super().__init__("This upload took too long. Start it again.")


class KnowledgeUploadLimitError(DomainError):
    status_code = 429
    code = "upload_limit_reached"

    def __init__(self) -> None:
        super().__init__("Too many uploads started in the last hour. Try again later.")


def start_upload(
    session: Session,
    principal: Principal,
    store: FileStore,
    body: KnowledgeUploadStart,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> KnowledgeUploadTicket:
    when = now or datetime.now(UTC)
    tenant_id = service._tenant(principal)  # noqa: SLF001 - the module's own rule, shared on purpose
    if principal.user_id is None:
        raise service.InvalidKnowledgeFileError("Only a person can upload.")
    visibility = body.visibility.strip().lower()
    if visibility not in ("internal", "customer_visible"):
        raise service.InvalidKnowledgeFileError(
            "Visibility must be 'internal' or 'customer_visible'."
        )
    if visibility == "internal" and body.account_id is not None:
        raise service.InvalidKnowledgeFileError(
            "Internal documents cannot be linked to one account."
        )
    if body.account_id is not None:
        from app.modules.accounts import api as accounts_api

        if not accounts_api.is_readable_account(session, principal, body.account_id):
            raise service.InvalidKnowledgeFileError("The selected account is not available.")
    if body.replaces_document_id is not None:
        previous = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.id == body.replaces_document_id,
            )
        )
        if previous is None or previous.is_archived:
            raise service.InvalidKnowledgeFileError("The document to replace is not available.")
    max_bytes = settings.files_max_bytes
    if body.size_bytes > max_bytes:
        raise service.FileTooLargeError(
            f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit."
        )
    name = rules.clean_file_name(body.file_name)
    kind = rules.ALLOWED.get(rules.extension(name))
    if kind is None:
        raise service.FileTypeNotAllowedError(f"Only {rules.ALLOWED_LABEL} files can be indexed.")
    started = session.scalar(
        select(func.count())
        .select_from(KnowledgeUpload)
        .where(
            KnowledgeUpload.tenant_id == tenant_id,
            KnowledgeUpload.created_by_user_id == principal.user_id,
            KnowledgeUpload.created_at >= when - timedelta(hours=1),
        )
    )
    if int(started or 0) >= settings.files_uploads_per_user_hour:
        raise KnowledgeUploadLimitError()
    row = KnowledgeUpload(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_by_user_id=principal.user_id,
        title=(body.title or "").strip()[:200] or rules.title_from(name),
        file_name=name,
        content_type=kind.content_type,
        declared_size=body.size_bytes,
        visibility=visibility,
        account_id=body.account_id,
        replaces_document_id=body.replaces_document_id,
        created_at=when,
    )
    session.add(row)
    session.flush()
    signed = store.signed_upload(
        pending_key(tenant_id, row.id), content_type=kind.content_type, max_bytes=body.size_bytes
    )
    return KnowledgeUploadTicket(
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
) -> KnowledgeDocument:
    when = now or datetime.now(UTC)
    if principal.tenant_id is None or principal.user_id is None:
        raise KnowledgeUploadNotFoundError()
    row = session.scalar(
        select(KnowledgeUpload)
        .where(
            KnowledgeUpload.tenant_id == principal.tenant_id,
            KnowledgeUpload.id == upload_id,
            KnowledgeUpload.created_by_user_id == principal.user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.status != "pending":
        raise KnowledgeUploadNotFoundError()
    key = pending_key(row.tenant_id, row.id)
    if row.created_at < when - timedelta(minutes=settings.files_upload_finish_minutes):
        row.status = "expired"
        session.flush()
        _forget(store, key)
        raise KnowledgeUploadExpiredError()
    try:
        found = store.stat(key)
    except StoredFileMissingError:
        raise KnowledgeUploadNotReceivedError() from None
    if found.size > row.declared_size or found.size > settings.files_max_bytes:
        _forget(store, key)
        raise service.FileTooLargeError("The file is larger than the size that was announced.")
    data = store.get(key)
    try:
        document = service.create_document(
            session,
            principal,
            store,
            title=row.title,
            file_name=row.file_name,
            content_type=row.content_type,
            data=data,
            max_bytes=settings.files_max_bytes,
            visibility=row.visibility,
            account_id=row.account_id,
            replaces_document_id=row.replaces_document_id,
        )
    except DomainError:
        _forget(store, key)  # a refused file is not kept, not even as pending
        raise
    session.flush()
    row.status = "finished"
    row.document_id = document.id
    row.finished_at = when
    session.flush()
    _forget(store, key)
    return document


def _forget(store: FileStore, key: str) -> None:
    try:
        store.delete(key)
    except Exception:  # noqa: BLE001 - the worker's sweep removes what is left
        logger.warning("could not remove a pending knowledge upload's file")


def delete_stale_uploads(
    session: Session, store: FileStore | None, now: datetime, *, tenant_id: uuid.UUID
) -> int:
    """Knowledge uploads started more than a day ago: the row goes, and any pending file left
    behind is removed from the store."""
    stale = list(
        session.scalars(
            select(KnowledgeUpload.id).where(
                KnowledgeUpload.tenant_id == tenant_id,
                KnowledgeUpload.created_at < now - STALE_AFTER,
            )
        )
    )
    if not stale:
        return 0
    if store is not None:
        for upload_id in stale:
            _forget(store, pending_key(tenant_id, upload_id))
    session.execute(
        delete(KnowledgeUpload).where(
            KnowledgeUpload.tenant_id == tenant_id, KnowledgeUpload.id.in_(stale)
        )
    )
    return len(stale)
