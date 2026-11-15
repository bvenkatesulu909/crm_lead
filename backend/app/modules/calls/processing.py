"""What the worker does with a queued recording (ADR 0030, step CA2).

    job ``call.process``  ->  the row must still be ``queued`` (a second run does nothing)
      1. the audio must exist, the ``call_audio`` switch must be on and the month's minutes left
      2. the length is read and refused above the limit (before any cleaning or paid service)
      3. the audio is cleaned (ffmpeg) and the cleaned copy stored next to the original
      4. the cleaned audio goes to the speech service WITH the language the rep chose
      5. the transcript is cleaned of hidden characters, stored with its timed segments, the
         seconds are added to the month's usage and the row is ``ready``

A recording that cannot be processed for a reason retrying will not fix (broken file, too long, no
speech, switched off, minutes used up) ends ``failed`` with a short code and the job finishes
normally. A temporary problem (the speech service is down) raises, so the outbox retries; when the
retries run out the dead-job hook marks the row ``failed``.

The transcript is a machine's guess at what two people said, and people's words are untrusted: it
is stored as plain text, shown as plain text, never passed to a model in this version.
"""

import asyncio
import logging
import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings
from app.core.outbox import Job, PermanentJobError
from app.core.screening import screen
from app.core.storage import FileStore, StoredFileMissingError
from app.modules.agents import api as agents_api
from app.modules.calls import audio, repository
from app.modules.calls.models import CallRecording
from app.modules.identity import api as identity_api
from app.modules.voice import api as voice_api

logger = logging.getLogger(__name__)

JOB_KIND = "call.process"
AGENT_KEY = "call_audio"
MAX_TRANSCRIPT_CHARS = 500_000
MAX_SEGMENTS = 20_000
MAX_SEGMENT_CHARS = 2_000
TRUNCATED = " [transcript cut here]"

SpeechFactory = Callable[[], voice_api.SpeechProvider | None]


def audit_system(
    session: Session, tenant_id: uuid.UUID, row: CallRecording, action: str, **changes: object
) -> None:
    record_audit(
        session,
        identity_api.automation_principal(session, tenant_id),
        action=action,
        entity_type="call_recording",
        entity_id=row.id,
        changes={"lead_id": str(row.lead_id), **changes},
    )


def _fail(session: Session, tenant_id: uuid.UUID, row: CallRecording, code: str) -> None:
    row.status = "failed"
    row.failure_code = code
    session.flush()
    audit_system(session, tenant_id, row, "call.failed", code=code)


def clean_text(value: str, limit: int) -> str:
    """Hidden characters and markup out; links and addresses stay (they were spoken or read out).
    Cut at ``limit`` with a marker."""
    cleaned = screen(value, strip_links=False, strip_addresses=False).clean
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - len(TRUNCATED)] + TRUNCATED
    return cleaned


def month_seconds_used(session: Session, tenant_id: uuid.UUID, now: datetime) -> int:
    current = agents_api.effective(session, tenant_id, AGENT_KEY, agents_api.Limits.default(), now)
    return current.input_tokens + current.output_tokens


def process(
    session: Session,
    job: Job,
    *,
    store: FileStore,
    cleaner: audio.Cleaner,
    speech: SpeechFactory,
    settings: Settings,
    now: datetime | None = None,
) -> None:
    when = now or datetime.now(UTC)
    try:
        call_id = uuid.UUID(str(job.payload["call_id"]))
        lead_id = uuid.UUID(str(job.payload["lead_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("bad job payload") from None
    row = repository.lock_of_lead(session, job.tenant_id, lead_id, call_id)
    if row is None or row.status != "queued":
        return  # gone, or already done by an earlier run of this job
    tenant_id = job.tenant_id

    if row.original_key is None or row.audio_deleted_at is not None:
        _fail(session, tenant_id, row, "audio_deleted")
        return
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, agents_api.Limits.default(), when)
    except agents_api.AgentUnavailableError:
        _fail(session, tenant_id, row, "call_audio_off")
        return
    if month_seconds_used(session, tenant_id, when) >= settings.calls_monthly_minutes * 60:
        _fail(session, tenant_id, row, "budget_reached")
        return

    try:
        original = store.get(row.original_key)
    except StoredFileMissingError:
        _fail(session, tenant_id, row, "audio_deleted")
        return

    try:
        seconds = cleaner.duration_seconds(original, row.file_name)
        if seconds > settings.calls_max_minutes * 60:
            _fail(session, tenant_id, row, "too_long")
            return
        cleaned = cleaner.clean(original, row.file_name)
    except audio.AudioUnreadableError:
        _fail(session, tenant_id, row, "unreadable")
        return
    except audio.AudioToolMissingError:
        raise PermanentJobError("audio tool is not installed") from None

    clean_key = f"{row.original_key}-clean"
    store.put(clean_key, cleaned, audio.CLEAN_CONTENT_TYPE)
    row.clean_key = clean_key

    provider = speech()
    if provider is None:
        raise PermanentJobError("speech service is not set up")
    try:
        transcript = asyncio.run(
            provider.transcribe_timed(
                cleaned, f"call{audio.CLEAN_SUFFIX}", audio.CLEAN_CONTENT_TYPE, row.language
            )
        )
    except voice_api.NoSpeechError:
        row.duration_seconds = math.ceil(seconds)
        _fail(session, tenant_id, row, "no_speech")
        return
    # Any other speech error is temporary: it propagates, the outbox retries, and the dead-job
    # hook marks the row failed when the retries run out.

    row.transcript_text = clean_text(transcript.text, MAX_TRANSCRIPT_CHARS)
    row.transcript_segments = [
        {
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "text": clean_text(segment.text, MAX_SEGMENT_CHARS),
        }
        for segment in transcript.segments[:MAX_SEGMENTS]
    ]
    row.engine = transcript.engine[:60]
    row.duration_seconds = math.ceil(seconds)
    row.status = "ready"
    row.failure_code = None
    session.flush()
    agents_api.record_usage(
        session,
        tenant_id,
        AGENT_KEY,
        input_tokens=math.ceil(seconds),
        output_tokens=0,
        limits=agents_api.Limits.default(),
        now=when,
    )
    audit_system(
        session,
        tenant_id,
        row,
        "call.transcribed",
        seconds=math.ceil(seconds),
        language=row.language,
        segments=len(row.transcript_segments),
    )


def on_dead(session: Session, job: Job, _error: str) -> None:
    """The retries ran out: the recording is ``failed`` (the job's error text is not copied)."""
    try:
        call_id = uuid.UUID(str(job.payload["call_id"]))
        lead_id = uuid.UUID(str(job.payload["lead_id"]))
    except (KeyError, ValueError):
        return
    row = repository.lock_of_lead(session, job.tenant_id, lead_id, call_id)
    if row is not None and row.status in {"queued", "processing"}:
        _fail(session, job.tenant_id, row, "processing_failed")
