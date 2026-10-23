"""Public interface of the workflows module (used by the worker)."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.events import Event, EventHandler
from app.modules.workflows import catalogue, service

__all__ = ["event_subscribers", "run_schedules"]


def event_subscribers(hourly_limit: int) -> dict[str, list[EventHandler]]:
    """{event name: [handler]} for every event a rule can be triggered by."""

    def handle(session: Session, event: Event) -> None:
        service.on_event(session, event, hourly_limit=hourly_limit)

    return {name: [handle] for name in catalogue.EVENT_RECORD_KEY}


def run_schedules(
    session: Session,
    now: datetime,
    *,
    hourly_limit: int,
    tenant_id: uuid.UUID | None = None,
) -> int:
    return service.run_schedules(session, now, hourly_limit=hourly_limit, tenant_id=tenant_id)
