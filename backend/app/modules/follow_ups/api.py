"""Public interface of the follow_ups module (ADR 0036). Other modules import only this."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.follow_ups import service

__all__ = ["run_schedules"]


def run_schedules(
    session: Session, now: datetime, *, tenant_id: uuid.UUID, platform_enabled: bool = True
) -> int:
    """Worker scheduler: make the due follow-up drafts of one organisation. Returns how many."""
    return service.scan(session, now, tenant_id=tenant_id, platform_enabled=platform_enabled).made
