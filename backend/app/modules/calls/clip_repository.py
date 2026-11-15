"""Queries of call clips (ADR 0033). Every query names the tenant (and RLS checks it again).
This file does not import the service: the recording's retention in the service calls
``forget_audio``."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.storage import FileStore
from app.modules.calls.models import CallClip


def add(session: Session, row: CallClip) -> CallClip:
    session.add(row)
    session.flush()
    return row


def list_of_recording(
    session: Session, tenant_id: uuid.UUID, recording_id: uuid.UUID
) -> list[CallClip]:
    """In the order they appear in the call (then oldest first, ties broken by id)."""
    return list(
        session.scalars(
            select(CallClip)
            .where(CallClip.tenant_id == tenant_id, CallClip.recording_id == recording_id)
            .order_by(CallClip.start_ms, CallClip.created_at, CallClip.id)
        )
    )


def get_of_recording(
    session: Session, tenant_id: uuid.UUID, recording_id: uuid.UUID, clip_id: uuid.UUID
) -> CallClip | None:
    return session.scalar(
        select(CallClip).where(
            CallClip.tenant_id == tenant_id,
            CallClip.recording_id == recording_id,
            CallClip.id == clip_id,
        )
    )


def get_in_tenant(session: Session, tenant_id: uuid.UUID, clip_id: uuid.UUID) -> CallClip | None:
    return session.scalar(
        select(CallClip)
        .where(CallClip.tenant_id == tenant_id, CallClip.id == clip_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def count_of_recording(session: Session, tenant_id: uuid.UUID, recording_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CallClip)
            .where(CallClip.tenant_id == tenant_id, CallClip.recording_id == recording_id)
        )
        or 0
    )


def count_since(session: Session, tenant_id: uuid.UUID, since: datetime) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CallClip)
            .where(CallClip.tenant_id == tenant_id, CallClip.created_at >= since)
        )
        or 0
    )


def forget_audio(
    session: Session,
    store: FileStore,
    tenant_id: uuid.UUID,
    recording_id: uuid.UUID,
    when: datetime,
) -> int:
    """The recording's audio is gone, so its clips' audio goes with it (ADR 0033, CL5): the files
    are deleted and each clip is marked; its title, note and transcript lines stay."""
    gone = 0
    for clip in list_of_recording(session, tenant_id, recording_id):
        if clip.audio_deleted_at is not None:
            continue
        if clip.clip_key:
            store.delete(clip.clip_key)
        clip.audio_deleted_at = when
        gone += 1
    session.flush()
    return gone
