"""Domain events (ADR 0006): "something happened" messages between modules, via the outbox.

A module calls ``publish()`` in the SAME transaction as its change; the event is stored as an
outbox job ``event.<name>``. The worker later hands it to every subscriber of that name
(notifications, workflow rules, …), which run in one transaction and are retried together.

Rules:
- Names come from the fixed catalogue below (docs/workflows.md describes each one).
- ``data`` holds IDs and short codes only - never names, e-mail addresses or other personal
  data. Subscribers look up what they need through the owning module's api.py.
- Subscribers must be safe to run twice (the event's id is the outbox job's id - use it to
  avoid duplicates).
- ``depth`` counts how many automatic steps led here; workflow rules stop at MAX_DEPTH, so
  rules can't trigger each other forever.
"""

import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.outbox import Job, JobHandler, PermanentJobError, enqueue

EVENT_NAMES = frozenset(
    {
        "lead.assigned",
        "activity.assigned",
        "activity.reminder_due",
        "quote.approval_requested",
        "quote.approved",
        "quote.rejected",
        "quote.accepted",
        "quote.declined",
        "ticket.assigned",
        "ticket.customer_replied",
        "order.status_changed",
        "contract.activated",
        "contract.terminated",
        "contract.renewal_due",
        "contract.expired",
        "communication.email_failed",
        "public_chat.lead_captured",
    }
)
MAX_DEPTH = 3
PREFIX = "event."
# Depth of the automatic step currently running (0 = a person did it). Events published while
# a workflow rule acts inherit it, so chains of rules are counted and stopped at MAX_DEPTH.
_CAUSE_DEPTH: ContextVar[int] = ContextVar("event_cause_depth", default=0)


@contextmanager
def caused_by_automation(depth: int) -> Iterator[None]:
    """Everything published inside this block carries at least ``depth``."""
    token = _CAUSE_DEPTH.set(depth)
    try:
        yield
    finally:
        _CAUSE_DEPTH.reset(token)


@dataclass(frozen=True)
class Event:
    id: uuid.UUID  # the outbox job id: unique per published event
    tenant_id: uuid.UUID
    name: str
    data: Mapping[str, Any]
    depth: int


EventHandler = Callable[[Session, Event], None]


def publish(
    session: Session,
    tenant_id: uuid.UUID,
    name: str,
    data: dict[str, Any],
    *,
    depth: int = 0,
) -> uuid.UUID:
    """Record that ``name`` happened; delivered after the caller's transaction commits."""
    if name not in EVENT_NAMES:
        raise ValueError(f"unknown event {name!r} - add it to EVENT_NAMES and the docs")
    job = enqueue(
        session,
        tenant_id=tenant_id,
        kind=PREFIX + name,
        payload={"data": data, "depth": max(depth, _CAUSE_DEPTH.get())},
    )
    return job.id


def uuid_of(event: Event, key: str) -> uuid.UUID:
    """A UUID from the event data; a malformed event can't get better by retrying."""
    try:
        return uuid.UUID(str(event.data[key]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError(f"event {event.name} without a valid {key}") from exc


def dispatcher(subscribers: Mapping[str, Sequence[EventHandler]]) -> dict[str, JobHandler]:
    """Outbox job handlers for every event name (names without subscribers just finish)."""

    def handler_for(name: str) -> JobHandler:
        def handle(session: Session, job: Job) -> None:
            event = Event(
                job.id,
                job.tenant_id,
                name,
                dict(job.payload.get("data") or {}),
                int(job.payload.get("depth") or 0),
            )
            for subscriber in subscribers.get(name, ()):
                subscriber(session, event)

        return handle

    return {PREFIX + name: handler_for(name) for name in EVENT_NAMES}
