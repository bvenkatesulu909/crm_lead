"""Call recordings (ADR 0030): start an upload, finish it, list, read, listen, delete the audio.

Like the other direct uploads (ADR 0025) the file goes from the browser straight to the file store:

    start  - the lead must be readable (else 404), the feature switched on for the organisation,
             the buyer's consent given, the type allowed by name, the size within the limit and the
             person's and the organisation's allowance not used up; then ONE row and a five-minute
             signed link for ``pending/{tenant}/{recording}``.
    finish - the row is locked and must be this person's, still uploading and not too old; the
             stored size is checked; the first bytes must be the audio type the name claims; the
             file is copied inside the store to its permanent key and the pending copy removed; the
             row is ``queued`` for processing (the worker comes in step CA2).

Nothing here commits - the router commits once (and also after a refusal of the FILE, so the row
shows ``failed`` with its reason). Audit entries hold ids and codes, never names or text.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.storage import FileStore, StoredFileMissingError, object_key, pending_key
from app.modules.agents import api as agents_api
from app.modules.calls import repository, rules
from app.modules.calls.models import CallRecording
from app.modules.calls.schemas import (
    CallDetail,
    CallPage,
    CallRead,
    ListenLink,
    UploadStart,
    UploadTicket,
)
from app.modules.leads import api as leads_api

logger = logging.getLogger(__name__)

AGENT_KEY = "call_audio"
STALE_AFTER = timedelta(days=1)
LISTEN_SECONDS = 60


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # Same message whether the lead doesn't exist, belongs to another tenant or isn't yours.
        super().__init__("Lead not found.")


class CallNotFoundError(NotFoundError):
    code = "call_not_found"

    def __init__(self) -> None:
        super().__init__(
            "The recording doesn't exist, isn't yours to finish, or was already finished."
        )


class CallAudioUnavailableError(DomainError):
    status_code = 503
    code = "call_audio_unavailable"

    def __init__(self) -> None:
        super().__init__("Call recordings are switched off for your organisation.")


class CallInvalidError(DomainError):
    status_code = 422
    code = "call_invalid"


class CallTypeNotAllowedError(DomainError):
    status_code = 422
    code = "call_type_not_allowed"


class TooLargeError(DomainError):
    status_code = 413
    code = "call_too_large"


class LimitReachedError(DomainError):
    status_code = 429
    code = "call_limit_reached"

    def __init__(self) -> None:
        super().__init__("Too many recordings were started. Try again later.")


class NotReceivedError(ConflictError):
    code = "call_not_received"

    def __init__(self) -> None:
        super().__init__("The file has not arrived in the file store yet. Send it, then finish.")


class UploadExpiredError(DomainError):
    status_code = 410
    code = "call_upload_expired"

    def __init__(self) -> None:
        super().__init__("This upload took too long. Start it again.")


class NotAudioError(DomainError):
    status_code = 422
    code = "call_not_audio"

    def __init__(self) -> None:
        super().__init__("The file is not the kind of audio its name says. It was not kept.")


class NotReadyError(ConflictError):
    code = "call_not_ready"

    def __init__(self) -> None:
        super().__init__("There is no audio to listen to yet.")


class AudioDeletedError(DomainError):
    status_code = 410
    code = "call_audio_deleted"

    def __init__(self) -> None:
        super().__init__("The audio of this recording was deleted.")


# The two refusals of the FILE (not of the request): the row is kept as ``failed``, so the router
# commits before it answers.
FILE_REFUSALS = (NotAudioError, TooLargeError)


def _tenant_and_user(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise LeadNotFoundError()
    return principal.tenant_id, principal.user_id


def _require_lead(session: Session, principal: Principal, lead_id: uuid.UUID) -> uuid.UUID:
    tenant_id, _ = _tenant_and_user(principal)
    if not leads_api.is_readable_lead(session, principal, lead_id):
        raise LeadNotFoundError()
    return tenant_id


def _forget(store: FileStore, key: str) -> None:
    try:
        store.delete(key)
    except Exception:  # noqa: BLE001 - the stale-upload sweep removes what is left
        logger.warning("could not remove a pending recording's file")


def _audit(
    session: Session, principal: Principal, row: CallRecording, action: str, **changes: object
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type="call_recording",
        entity_id=row.id,
        changes={"lead_id": str(row.lead_id), **changes},
    )


def _read(row: CallRecording) -> dict[str, object]:
    return {
        "id": row.id,
        "lead_id": row.lead_id,
        "added_by_user_id": row.added_by_user_id,
        "language": row.language,
        "status": row.status,
        "failure_code": row.failure_code,
        "file_name": row.file_name,
        "size_bytes": row.size_bytes,
        "duration_seconds": row.duration_seconds,
        "consent_confirmed_at": row.consent_confirmed_at,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "audio_available": row.original_key is not None and row.audio_deleted_at is None,
        "audio_deleted_at": row.audio_deleted_at,
        "has_transcript": row.transcript_text is not None,
        "engine": row.engine,
    }


def start_upload(
    session: Session,
    principal: Principal,
    store: FileStore,
    lead_id: uuid.UUID,
    body: UploadStart,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> UploadTicket:
    when = now or datetime.now(UTC)
    tenant_id = _require_lead(session, principal, lead_id)
    _, user_id = _tenant_and_user(principal)
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, agents_api.Limits.default(), when)
    except agents_api.AgentUnavailableError:
        raise CallAudioUnavailableError() from None
    try:
        rules.check_consent(body.consent)
        name = rules.clean_file_name(body.file_name)
        kind = rules.kind_of(name)
        rules.check_size(body.size_bytes, settings.calls_max_bytes)
    except rules.CallTypeError as exc:
        raise CallTypeNotAllowedError(str(exc)) from None
    except rules.CallTooLargeError as exc:
        raise TooLargeError(str(exc)) from None
    except rules.CallRuleError as exc:
        raise CallInvalidError(str(exc)) from None
    if (
        repository.count_started(session, tenant_id, when - timedelta(hours=1), user_id=user_id)
        >= settings.calls_uploads_per_user_hour
        or repository.count_started(session, tenant_id, when - timedelta(days=1))
        >= settings.calls_uploads_per_tenant_day
    ):
        raise LimitReachedError()
    row = repository.add(
        session,
        CallRecording(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            lead_id=lead_id,
            added_by_user_id=user_id,
            language=body.language,
            consent_confirmed_at=when,
            file_name=name,
            content_type=rules.AUDIO_TYPES[kind],
            declared_size=body.size_bytes,
            status="uploading",
            created_at=when,
        ),
    )
    signed = store.signed_upload(
        pending_key(tenant_id, row.id),
        content_type=row.content_type,
        max_bytes=body.size_bytes,
        hard_limit=settings.calls_max_bytes,
    )
    return UploadTicket(
        call_id=row.id,
        url=signed.url,
        fields=signed.fields,
        expires_at=signed.expires_at,
        max_bytes=body.size_bytes,
    )


def finish_upload(
    session: Session,
    principal: Principal,
    store: FileStore,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> CallRead:
    when = now or datetime.now(UTC)
    tenant_id = _require_lead(session, principal, lead_id)
    _, user_id = _tenant_and_user(principal)
    row = repository.lock_of_lead(session, tenant_id, lead_id, call_id)
    if row is None or row.status != "uploading" or row.added_by_user_id != user_id:
        raise CallNotFoundError()
    pending = pending_key(tenant_id, row.id)
    if row.created_at < when - timedelta(minutes=settings.calls_upload_finish_minutes):
        _forget(store, pending)
        raise UploadExpiredError()
    try:
        found = store.stat(pending)
    except StoredFileMissingError:
        raise NotReceivedError() from None
    if found.size > row.declared_size or found.size > settings.calls_max_bytes:
        _refuse(session, store, row, pending, "too_large")
        raise TooLargeError("The file is larger than the size that was announced.")
    kind = rules.kind_of(row.file_name)
    try:
        head = store.read_head(pending, rules.HEAD_BYTES)
    except StoredFileMissingError:
        raise NotReceivedError() from None
    if not rules.looks_like(kind, head):
        _refuse(session, store, row, pending, "not_audio")
        raise NotAudioError()
    original = object_key(tenant_id, "calls", lead_id, row.id)
    store.copy(pending, original)
    _forget(store, pending)
    row.size_bytes = found.size
    row.original_key = original
    row.status = "queued"
    row.finished_at = when
    session.flush()
    _audit(session, principal, row, "call.added", language=row.language)
    return CallRead.model_validate(_read(row))


def _refuse(
    session: Session, store: FileStore, row: CallRecording, pending: str, code: str
) -> None:
    """A refused file is not kept, not even as pending; the row says why."""
    _forget(store, pending)
    row.status = "failed"
    row.failure_code = code
    session.flush()


def list_calls(session: Session, principal: Principal, lead_id: uuid.UUID) -> CallPage:
    tenant_id = _require_lead(session, principal, lead_id)
    rows = repository.list_of_lead(session, tenant_id, lead_id)
    return CallPage(items=[CallRead.model_validate(_read(r)) for r in rows])


def get_call(
    session: Session, principal: Principal, lead_id: uuid.UUID, call_id: uuid.UUID
) -> CallDetail:
    tenant_id = _require_lead(session, principal, lead_id)
    row = repository.get_of_lead(session, tenant_id, lead_id, call_id)
    if row is None:
        raise CallNotFoundError()
    return CallDetail.model_validate(
        {**_read(row), "transcript": row.transcript_text, "segments": row.transcript_segments}
    )


def listen_link(
    session: Session,
    principal: Principal,
    store: FileStore,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
) -> ListenLink:
    tenant_id = _require_lead(session, principal, lead_id)
    row = repository.get_of_lead(session, tenant_id, lead_id, call_id)
    if row is None:
        raise CallNotFoundError()
    if row.audio_deleted_at is not None:
        raise AudioDeletedError()
    key = row.clean_key or row.original_key
    if key is None:
        raise NotReadyError()
    copy: Literal["original", "cleaned"] = "cleaned" if row.clean_key else "original"
    url = store.signed_download(key, file_name=row.file_name)
    _audit(session, principal, row, "call.listened", copy=copy)
    return ListenLink(url=url, expires_in_seconds=LISTEN_SECONDS, which=copy)


def delete_audio(
    session: Session,
    principal: Principal,
    store: FileStore,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CallRead:
    """Delete the audio files (the original and the cleaned copy). The row, its consent record and
    its transcript stay. Deleting twice is not an error."""
    when = now or datetime.now(UTC)
    tenant_id = _require_lead(session, principal, lead_id)
    row = repository.lock_of_lead(session, tenant_id, lead_id, call_id)
    if row is None:
        raise CallNotFoundError()
    if row.audio_deleted_at is None and (row.original_key or row.clean_key):
        for key in (row.original_key, row.clean_key):
            if key:
                store.delete(key)
        row.audio_deleted_at = when
        session.flush()
        _audit(session, principal, row, "call.audio_deleted")
    return CallRead.model_validate(_read(row))


def expire_stale(
    session: Session, store: FileStore | None, now: datetime, *, tenant_id: uuid.UUID
) -> int:
    """Uploads started more than a day ago and never finished: the row becomes ``expired`` and any
    pending file left behind is removed from the store."""
    stale = repository.stale_uploads(session, tenant_id, now - STALE_AFTER)
    for row in stale:
        if store is not None:
            _forget(store, pending_key(tenant_id, row.id))
        row.status = "expired"
    session.flush()
    return len(stale)
