"""Asking for an adjusted copy of a photo, and making it (ADR 0039, PE2).

The request is quick and checked completely before anything is queued: the person's permissions, the
organisation's switch, the photo (an uploaded JPEG or PNG on a record the person may see), what was
asked for (only the allowed adjustments, each within its cap), the limits. The work is a worker
job. The original is only read; the copy is a new document next to it.
"""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.outbox import Job, PermanentJobError, enqueue
from app.core.storage import FileStore, StoredFileMissingError
from app.modules.agents import api as agents_api
from app.modules.branding import api as branding_api
from app.modules.documents import api as documents_api
from app.modules.identity import api as identity_api
from app.modules.photo_enhancer import repository, rules
from app.modules.photo_enhancer.models import PhotoEnhancement

logger = logging.getLogger(__name__)

AGENT_KEY = "photo_enhancer"
JOB_KIND = "photo.enhance"
TOOL_VERSION = "pe1"
ENTITY = "photo_enhancement"
IMAGE_TYPES = ("image/jpeg", "image/png")


class PhotoNotFoundError(NotFoundError):
    code = "photo_not_found"

    def __init__(self) -> None:
        # The same answer whether the photo does not exist, is another organisation's or is on a
        # record the person may not see.
        super().__init__("Photo not found.")


class CopyNotFoundError(NotFoundError):
    code = "photo_copy_not_found"

    def __init__(self) -> None:
        super().__init__("Adjusted copy not found.")


class PhotoEnhancerUnavailableError(DomainError):
    status_code = 503
    code = "photo_enhancer_unavailable"

    def __init__(self) -> None:
        super().__init__("The photo enhancer is switched off for your organisation.")


class NotAPhotoError(DomainError):
    status_code = 422
    code = "photo_not_an_image"

    def __init__(self) -> None:
        super().__init__("Only JPEG and PNG photos can be adjusted.")


class PhotoRequestError(DomainError):
    """What was asked for is refused by the rules (above a cap, not on the list, ...)."""

    status_code = 422

    def __init__(self, error: rules.PhotoRuleError) -> None:
        super().__init__(str(error))
        self.code = f"photo_{error.code}"


class PhotoLimitReachedError(DomainError):
    status_code = 429
    code = "photo_limit_reached"

    def __init__(self, message: str = "Too many photos were adjusted. Try again later.") -> None:
        super().__init__(message)


def _tenant_and_user(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise PhotoNotFoundError()
    return principal.tenant_id, principal.user_id


def _check_may_enhance(principal: Principal) -> None:
    if not (
        principal.has_permission(Permission.PHOTO_ENHANCE)
        and principal.has_permission(Permission.DOCUMENT_WRITE)
    ):
        raise ForbiddenError("You are not allowed to adjust photos.")


def _photo(
    session: Session, principal: Principal, original_document_id: uuid.UUID
) -> documents_api.DocumentRef:
    tenant_id, _ = _tenant_and_user(principal)
    ref = documents_api.document_ref(session, tenant_id, original_document_id)
    if ref is None or not documents_api.can_read_document(session, principal, ref):
        raise PhotoNotFoundError()
    return ref


def _audit(
    session: Session, principal: Principal, row: PhotoEnhancement, action: str, **changes: object
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type=ENTITY,
        entity_id=row.id,
        changes={"document_id": str(row.original_document_id), **changes},
    )


def request_enhancement(
    session: Session,
    principal: Principal,
    original_document_id: uuid.UUID,
    raw_operations: dict[str, Any],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> PhotoEnhancement:
    """Check everything, record the request and queue the job. The caller commits."""
    when = now or datetime.now(UTC)
    tenant_id, user_id = _tenant_and_user(principal)
    _check_may_enhance(principal)
    if settings.photo_enhancer_disabled:
        raise PhotoEnhancerUnavailableError()
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, agents_api.Limits.default(), when)
    except agents_api.AgentUnavailableError:
        raise PhotoEnhancerUnavailableError() from None
    ref = _photo(session, principal, original_document_id)
    if ref.content_type not in IMAGE_TYPES or ref.size_bytes > rules.MAX_UPLOAD_BYTES:
        raise NotAPhotoError()
    try:
        operations = rules.operations_from_dict(raw_operations)
    except rules.PhotoRuleError as exc:
        raise PhotoRequestError(exc) from None
    if (
        operations.watermark is not None
        and operations.watermark.kind == "logo"
        and branding_api.branding_for_deck(session, tenant_id).logo_png is None
    ):
        raise PhotoRequestError(
            rules.PhotoRuleError("watermark_logo_missing", "The organisation has no logo to use.")
        )
    if (
        repository.count_of_original(session, tenant_id, ref.id)
        >= settings.photo_enhancements_per_original
    ):
        raise PhotoLimitReachedError(
            f"This photo already has {settings.photo_enhancements_per_original} adjusted copies. "
            "Delete one first."
        )
    if (
        repository.count_started(session, tenant_id, when - timedelta(hours=1), user_id=user_id)
        >= settings.photo_enhancements_per_user_hour
        or repository.count_started(session, tenant_id, when - timedelta(days=1))
        >= settings.photo_enhancements_per_tenant_day
    ):
        raise PhotoLimitReachedError()
    row = repository.add(
        session,
        PhotoEnhancement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            original_document_id=ref.id,
            requested_by_user_id=user_id,
            status="queued",
            operations=rules.operations_to_dict(operations),
            tool_version=TOOL_VERSION,
            created_at=when,
        ),
    )
    enqueue(session, tenant_id=tenant_id, kind=JOB_KIND, payload={"enhancement_id": str(row.id)})
    _audit(session, principal, row, "photo.enhancement_requested", steps=rules.describe(operations))
    return row


def list_copies(
    session: Session, principal: Principal, original_document_id: uuid.UUID
) -> list[PhotoEnhancement]:
    """The requests made for a photo (newest first), for anyone who may read the photo."""
    tenant_id, _ = _tenant_and_user(principal)
    if not principal.has_permission(Permission.DOCUMENT_READ):
        raise ForbiddenError("You are not allowed to see documents.")
    ref = _photo(session, principal, original_document_id)
    return repository.list_of_original(session, tenant_id, ref.id)


def _load_copy(
    session: Session, principal: Principal, enhancement_id: uuid.UUID
) -> tuple[PhotoEnhancement, documents_api.DocumentRef]:
    tenant_id, _ = _tenant_and_user(principal)
    row = repository.get(session, tenant_id, enhancement_id)
    if row is None:
        raise CopyNotFoundError()
    try:
        ref = _photo(session, principal, row.original_document_id)
    except PhotoNotFoundError:
        raise CopyNotFoundError() from None
    return row, ref


def copy_link(
    session: Session, principal: Principal, store: FileStore, enhancement_id: uuid.UUID
) -> documents_api.DownloadLink:
    """A 60-second link to a finished copy, for anyone who may read the original photo."""
    tenant_id, _ = _tenant_and_user(principal)
    if not principal.has_permission(Permission.DOCUMENT_READ):
        raise ForbiddenError("You are not allowed to see documents.")
    row, _ref = _load_copy(session, principal, enhancement_id)
    if row.status != "ready" or row.derived_document_id is None:
        raise CopyNotFoundError()
    return documents_api.download_link(session, store, tenant_id, row.derived_document_id)


def delete_copy(session: Session, principal: Principal, enhancement_id: uuid.UUID) -> str | None:
    """Delete one request and its copy (never the original). Returns the copy's file key, which
    the caller removes from the store after the commit."""
    tenant_id, _ = _tenant_and_user(principal)
    _check_may_enhance(principal)
    row, _ref = _load_copy(session, principal, enhancement_id)
    key = None
    if row.derived_document_id is not None:
        key = documents_api.delete_derived_document(session, tenant_id, row.derived_document_id)
    else:
        session.delete(row)
        session.flush()
    _audit(session, principal, row, "photo.copy_deleted")
    return key


def remove_file(store: FileStore, key: str | None) -> None:
    if key is None:
        return
    try:
        store.delete(key)
    except Exception:  # noqa: BLE001 - an orphaned file is harmless; the row is gone
        logger.warning("could not remove a deleted photo copy's file")


# --- the worker ----------------------------------------------------------------------------


def _system_audit(
    session: Session, tenant_id: uuid.UUID, row: PhotoEnhancement, action: str, **changes: object
) -> None:
    record_audit(
        session,
        identity_api.automation_principal(session, tenant_id),
        action=action,
        entity_type=ENTITY,
        entity_id=row.id,
        changes={"document_id": str(row.original_document_id), **changes},
    )


def _fail(session: Session, tenant_id: uuid.UUID, row: PhotoEnhancement, code: str) -> None:
    row.status = "failed"
    row.failure_code = code[:30]
    row.finished_at = datetime.now(UTC)
    session.flush()
    _system_audit(session, tenant_id, row, "photo.failed", code=code)


def _enhancement_id(job: Job) -> uuid.UUID:
    try:
        return uuid.UUID(str(job.payload["enhancement_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("bad job payload") from None


def process(
    session: Session,
    job: Job,
    *,
    store: FileStore,
    settings: Settings,
    now: datetime | None = None,
) -> None:
    """Job ``photo.enhance``. The row must still be ``queued`` (a second run does nothing). A reason
    retrying cannot fix ends the row ``failed`` with a short code and the job finishes normally; a
    store that is down raises, so the outbox retries."""
    when = now or datetime.now(UTC)
    tenant_id = job.tenant_id
    row = repository.lock(session, tenant_id, _enhancement_id(job))
    if row is None or row.status != "queued":
        return
    if settings.photo_enhancer_disabled:
        _fail(session, tenant_id, row, "photo_enhancer_off")
        return
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, agents_api.Limits.default(), when)
    except agents_api.AgentUnavailableError:
        _fail(session, tenant_id, row, "photo_enhancer_off")
        return
    ref = documents_api.document_ref(session, tenant_id, row.original_document_id)
    if ref is None or ref.content_type not in IMAGE_TYPES:
        _fail(session, tenant_id, row, "not_an_image")
        return
    try:
        _info, original = documents_api.read_document(
            session, store, tenant_id, row.original_document_id
        )
    except (StoredFileMissingError, documents_api.DocumentIntegrityError):
        _fail(session, tenant_id, row, "unreadable")
        return
    try:
        photo = rules.inspect(original)
        if (
            rules.estimated_memory_bytes(photo)
            > settings.photo_enhancer_max_memory_mb * 1024 * 1024
        ):
            _fail(session, tenant_id, row, "too_large")
            return
        operations = rules.operations_from_dict(row.operations)
        logo = (
            branding_api.branding_for_deck(session, tenant_id).logo_png
            if operations.watermark is not None and operations.watermark.kind == "logo"
            else None
        )
        result = rules.enhance(
            original,
            operations,
            logo_png=logo,
            deadline=time.monotonic() + settings.photo_enhancer_max_seconds,
        )
    except rules.PhotoRuleError as exc:
        _fail(session, tenant_id, row, exc.code)
        return
    stem = ref.file_name.rsplit(".", 1)[0][:140] or "photo"
    derived = documents_api.store_derived_document(
        session,
        store,
        tenant_id=tenant_id,
        original=ref,
        file_name=f"{stem}-enhanced.jpg",
        content_type="image/jpeg",
        data=result.jpeg,
        created_by_user_id=row.requested_by_user_id,
    )
    row.derived_document_id = derived.id
    row.applied = result.applied
    row.width = result.width
    row.height = result.height
    row.size_bytes = derived.size_bytes
    row.status = "ready"
    row.failure_code = None
    row.finished_at = when
    session.flush()
    agents_api.record_usage(
        session,
        tenant_id,
        AGENT_KEY,
        input_tokens=1,
        output_tokens=0,
        limits=agents_api.Limits.default(),
        now=when,
    )
    _system_audit(
        session,
        tenant_id,
        row,
        "photo.enhanced",
        steps=result.applied,
        width=result.width,
        height=result.height,
        size_bytes=derived.size_bytes,
    )


def on_dead(session: Session, job: Job, _error: str) -> None:
    """The retries ran out: the request is ``failed`` (the job's error text is not copied)."""
    try:
        enhancement_id = uuid.UUID(str(job.payload["enhancement_id"]))
    except (KeyError, ValueError):
        return
    row = repository.lock(session, job.tenant_id, enhancement_id)
    if row is not None and row.status == "queued":
        _fail(session, job.tenant_id, row, "processing_failed")
