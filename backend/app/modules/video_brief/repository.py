"""Queries of the saved video scripts. Every query names the organisation (row-level security is
the second wall, ADR 0009)."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.video_brief.models import VideoScript


def next_version(session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID) -> int:
    newest = session.scalar(
        select(func.max(VideoScript.version)).where(
            VideoScript.tenant_id == tenant_id, VideoScript.lead_id == lead_id
        )
    )
    return int(newest or 0) + 1


def count_saved_by(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, *, since: datetime
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(VideoScript)
            .where(
                VideoScript.tenant_id == tenant_id,
                VideoScript.created_by_user_id == user_id,
                VideoScript.created_at >= since,
            )
        )
        or 0
    )


def scripts_of(session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID) -> Sequence[VideoScript]:
    """Newest first."""
    return session.scalars(
        select(VideoScript)
        .where(VideoScript.tenant_id == tenant_id, VideoScript.lead_id == lead_id)
        .order_by(VideoScript.version.desc())
    ).all()
