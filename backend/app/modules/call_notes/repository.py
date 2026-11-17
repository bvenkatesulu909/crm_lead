"""Queries of the call notes. Every query names the organisation (row-level security is the second
wall, ADR 0009)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.call_notes.models import CallNote, CallNoteLine, CallNoteSettings


def framework_of(session: Session, tenant_id: uuid.UUID) -> str | None:
    return session.scalar(
        select(CallNoteSettings.framework).where(CallNoteSettings.tenant_id == tenant_id)
    )


def count_notes(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    recording_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> int:
    """Drafts stored since a moment, for the rate limits."""
    query = (
        select(func.count())
        .select_from(CallNote)
        .where(CallNote.tenant_id == tenant_id, CallNote.created_at >= since)
    )
    if recording_id is not None:
        query = query.where(CallNote.recording_id == recording_id)
    if user_id is not None:
        query = query.where(CallNote.requested_by_user_id == user_id)
    return int(session.scalar(query) or 0)


def next_version(session: Session, tenant_id: uuid.UUID, recording_id: uuid.UUID) -> int:
    newest = session.scalar(
        select(func.max(CallNote.version_no)).where(
            CallNote.tenant_id == tenant_id, CallNote.recording_id == recording_id
        )
    )
    return int(newest or 0) + 1


def add(session: Session, note: CallNote, lines: list[CallNoteLine]) -> CallNote:
    session.add(note)
    session.flush()
    for line in lines:
        line.call_note_id = note.id
        session.add(line)
    session.flush()
    return note


def newest(session: Session, tenant_id: uuid.UUID, recording_id: uuid.UUID) -> CallNote | None:
    return session.scalars(
        select(CallNote)
        .where(CallNote.tenant_id == tenant_id, CallNote.recording_id == recording_id)
        .order_by(CallNote.version_no.desc())
        .limit(1)
    ).first()


def lines_of(session: Session, tenant_id: uuid.UUID, note_id: uuid.UUID) -> list[CallNoteLine]:
    return list(
        session.scalars(
            select(CallNoteLine)
            .where(CallNoteLine.tenant_id == tenant_id, CallNoteLine.call_note_id == note_id)
            .order_by(CallNoteLine.position)
        )
    )
