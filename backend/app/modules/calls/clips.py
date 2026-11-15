"""Highlight clips of call recordings (ADR 0033): make one, list, listen, edit, delete, and the
worker job that cuts the audio. Services never commit; the router (or the worker) commits once.

    permission to add recordings ─► the lead must be readable (else 404) ─► the recording must be
    ``ready`` with its audio ─► the range lies inside it and is 3-120 seconds ─► the typed texts are
    cleaned ─► limits ─► the clip row (``queued``) ─► the job ``call.clip`` ─► audit

A clip is a copy of a buyer's voice, so it is only ever cut from the cleaned copy of a recording
that has consent, it is deleted together with the recording's audio, and it never leaves the
CRM (a 60-second signed link, like the recording itself).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.outbox import Job, PermanentJobError, enqueue
from app.core.storage import FileStore, StoredFileMissingError
from app.modules.calls import audio, clip_repository, clip_rules, repository, service
from app.modules.calls.models import CallClip, CallRecording
from app.modules.calls.schemas import ClipCreate, ClipEdit, ClipPage, ClipRead, ListenLink
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api

JOB_KIND = "call.clip"
PER_RECORDING = 20
PER_TENANT_DAY = 100
LISTEN_SECONDS = service.LISTEN_SECONDS


class ClipNotFoundError(NotFoundError):
    code = "clip_not_found"

    def __init__(self) -> None:
        super().__init__("Clip not found.")


class ClipInvalidError(DomainError):
    status_code = 422
    code = "clip_invalid"


class ClipLimitReachedError(DomainError):
    status_code = 429
    code = "clip_limit_reached"


def _tenant_and_user(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise service.LeadNotFoundError()
    return principal.tenant_id, principal.user_id


def _recording(
    session: Session, principal: Principal, lead_id: uuid.UUID, call_id: uuid.UUID
) -> CallRecording:
    """The recording, for a person who may read its lead (else 404, as for the recording itself)."""
    tenant_id, _ = _tenant_and_user(principal)
    if not leads_api.is_readable_lead(session, principal, lead_id):
        raise service.LeadNotFoundError()
    row = repository.get_of_lead(session, tenant_id, lead_id, call_id)
    if row is None:
        raise service.CallNotFoundError()
    return row


def _read(clip: CallClip, recording: CallRecording) -> ClipRead:
    return ClipRead(
        id=clip.id,
        recording_id=clip.recording_id,
        lead_id=recording.lead_id,
        made_by_user_id=clip.made_by_user_id,
        start_ms=clip.start_ms,
        end_ms=clip.end_ms,
        duration_ms=clip.end_ms - clip.start_ms,
        title=clip.title,
        note=clip.note,
        excerpt=clip.excerpt,
        status=clip.status,
        failure_code=clip.failure_code,
        created_at=clip.created_at,
        audio_available=clip.status == "ready" and clip.audio_deleted_at is None,
        audio_deleted_at=clip.audio_deleted_at,
    )


def _audit(
    session: Session, principal: Principal, clip: CallClip, action: str, **changes: object
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type="call_clip",
        entity_id=clip.id,
        changes={"recording_id": str(clip.recording_id), **changes},
    )


def _clip(
    session: Session, tenant_id: uuid.UUID, recording: CallRecording, clip_id: uuid.UUID
) -> CallClip:
    clip = clip_repository.get_of_recording(session, tenant_id, recording.id, clip_id)
    if clip is None:
        raise ClipNotFoundError()
    return clip


def _may_change(principal: Principal, clip: CallClip) -> bool:
    """The maker, and managers and administrators (who may read every lead)."""
    return clip.made_by_user_id == principal.user_id or principal.has_permission(
        Permission.LEAD_READ_ALL
    )


# --- people -----------------------------------------------------------------------------------


def create_clip(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    body: ClipCreate,
    *,
    now: datetime | None = None,
) -> ClipRead:
    when = now or datetime.now(UTC)
    tenant_id, user_id = _tenant_and_user(principal)
    recording = _recording(session, principal, lead_id, call_id)
    if recording.status != "ready":
        raise service.NotReadyError()
    if recording.audio_deleted_at is not None or recording.clean_key is None:
        raise service.AudioDeletedError()
    try:
        clip_rules.check_range(
            body.start_ms, body.end_ms, duration_seconds=recording.duration_seconds
        )
        title = clip_rules.clean_title(body.title)
        note = clip_rules.clean_note(body.note)
    except clip_rules.ClipRuleError as why:
        raise ClipInvalidError(str(why)) from None
    if clip_repository.count_of_recording(session, tenant_id, recording.id) >= PER_RECORDING:
        raise ClipLimitReachedError(f"A recording can have at most {PER_RECORDING} clips.")
    if clip_repository.count_since(session, tenant_id, when - timedelta(days=1)) >= PER_TENANT_DAY:
        raise ClipLimitReachedError("Your organisation reached its daily limit for clips.")
    clip = clip_repository.add(
        session,
        CallClip(
            tenant_id=tenant_id,
            recording_id=recording.id,
            made_by_user_id=user_id,
            start_ms=body.start_ms,
            end_ms=body.end_ms,
            title=title.text or "",
            note=note.text,
            excerpt=clip_rules.excerpt(recording.transcript_segments, body.start_ms, body.end_ms),
        ),
    )
    enqueue(session, tenant_id=tenant_id, kind=JOB_KIND, payload={"clip_id": str(clip.id)})
    # Ids, milliseconds and the KINDS of finding - never the title, the note or the lines.
    _audit(
        session,
        principal,
        clip,
        "call_clip.created",
        lead_id=str(recording.lead_id),
        start_ms=clip.start_ms,
        end_ms=clip.end_ms,
        findings=sorted({*title.findings, *note.findings}),
    )
    session.flush()
    return _read(clip, recording)


def list_clips(
    session: Session, principal: Principal, lead_id: uuid.UUID, call_id: uuid.UUID
) -> ClipPage:
    recording = _recording(session, principal, lead_id, call_id)
    rows = clip_repository.list_of_recording(session, recording.tenant_id, recording.id)
    return ClipPage(items=[_read(row, recording) for row in rows])


def listen_clip(
    session: Session,
    principal: Principal,
    store: FileStore,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    clip_id: uuid.UUID,
) -> ListenLink:
    recording = _recording(session, principal, lead_id, call_id)
    clip = _clip(session, recording.tenant_id, recording, clip_id)
    if clip.audio_deleted_at is not None:
        raise service.AudioDeletedError()
    if clip.status != "ready" or clip.clip_key is None:
        raise service.NotReadyError()
    # A fixed "save as" name: nothing a person typed goes into a header.
    url = store.signed_download(clip.clip_key, file_name=f"clip-{clip.start_ms}-{clip.end_ms}.mp3")
    _audit(session, principal, clip, "call_clip.listened", lead_id=str(recording.lead_id))
    return ListenLink(url=url, expires_in_seconds=LISTEN_SECONDS, which="cleaned")


def edit_clip(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    clip_id: uuid.UUID,
    body: ClipEdit,
) -> ClipRead:
    """Change the title and/or the note (nothing else about a clip can change)."""
    recording = _recording(session, principal, lead_id, call_id)
    clip = _clip(session, recording.tenant_id, recording, clip_id)
    if not _may_change(principal, clip):
        raise ForbiddenError("Only the person who made a clip, or a manager, may change it.")
    changed: list[str] = []
    findings: set[str] = set()
    try:
        if "title" in body.model_fields_set:
            title = clip_rules.clean_title(body.title)
            clip.title = title.text or ""
            changed.append("title")
            findings.update(title.findings)
        if "note" in body.model_fields_set:
            note = clip_rules.clean_note(body.note)
            clip.note = note.text
            changed.append("note")
            findings.update(note.findings)
    except clip_rules.ClipRuleError as why:
        raise ClipInvalidError(str(why)) from None
    if not changed:
        raise ClipInvalidError("Send a title or a note to change.")
    session.flush()
    _audit(
        session,
        principal,
        clip,
        "call_clip.edited",
        lead_id=str(recording.lead_id),
        fields=changed,
        findings=sorted(findings),
    )
    return _read(clip, recording)


def delete_clip(
    session: Session,
    principal: Principal,
    store: FileStore,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    clip_id: uuid.UUID,
) -> None:
    recording = _recording(session, principal, lead_id, call_id)
    clip = _clip(session, recording.tenant_id, recording, clip_id)
    if not _may_change(principal, clip):
        raise ForbiddenError("Only the person who made a clip, or a manager, may delete it.")
    if clip.clip_key and clip.audio_deleted_at is None:
        store.delete(clip.clip_key)
    _audit(session, principal, clip, "call_clip.deleted", lead_id=str(recording.lead_id))
    session.delete(clip)
    session.flush()


# --- the worker -------------------------------------------------------------------------------


def _fail(session: Session, tenant_id: uuid.UUID, clip: CallClip, code: str) -> None:
    clip.status = "failed"
    clip.failure_code = code
    session.flush()
    record_audit(
        session,
        identity_api.automation_principal(session, tenant_id),
        action="call_clip.failed",
        entity_type="call_clip",
        entity_id=clip.id,
        changes={"recording_id": str(clip.recording_id), "code": code},
    )


def process(session: Session, job: Job, *, store: FileStore, cleaner: audio.Cleaner) -> None:
    """Cut one clip. Safe to run twice (a ``ready`` clip is left alone). A recording whose audio is
    gone, a file that cannot be cut and a machine without ffmpeg end the clip as ``failed`` with a
    code; anything else is temporary and is retried by the outbox."""
    try:
        clip_id = uuid.UUID(str(job.payload["clip_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("the job has no valid clip id") from None
    clip = clip_repository.get_in_tenant(session, job.tenant_id, clip_id)
    if clip is None:
        raise PermanentJobError("clip not found")
    if clip.status != "queued":
        return
    recording = session.get(CallRecording, clip.recording_id)
    if recording is None or recording.audio_deleted_at is not None or not recording.clean_key:
        _fail(session, job.tenant_id, clip, "audio_deleted")
        return
    try:
        data = store.get(recording.clean_key)
    except StoredFileMissingError:
        _fail(session, job.tenant_id, clip, "audio_deleted")
        return
    try:
        cut = cleaner.cut(data, recording.file_name, clip.start_ms, clip.end_ms)
    except audio.AudioUnreadableError:
        _fail(session, job.tenant_id, clip, "unreadable")
        return
    except audio.AudioToolMissingError:
        _fail(session, job.tenant_id, clip, "audio_tool_missing")
        return
    key = f"{recording.original_key}-clip-{clip.id}"
    store.put(key, cut, audio.CLEAN_CONTENT_TYPE)
    clip.clip_key = key
    clip.status = "ready"
    clip.failure_code = None
    session.flush()


def on_dead(session: Session, job: Job, _error: str) -> None:
    """The retries ran out: the clip is ``failed`` (the job's error text is not copied)."""
    try:
        clip_id = uuid.UUID(str(job.payload["clip_id"]))
    except (KeyError, ValueError):
        return
    clip = clip_repository.get_in_tenant(session, job.tenant_id, clip_id)
    if clip is not None and clip.status == "queued":
        _fail(session, job.tenant_id, clip, "processing_failed")
