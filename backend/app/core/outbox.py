"""Outbox jobs: work that must happen after a change is saved, outside the HTTP request (ADR 0005).

How it fits together:

1. A service calls ``enqueue()`` in the SAME transaction as its change. If the change is
   rolled back, the job disappears with it; if it is committed, the job is guaranteed to exist.
2. The worker (``python -m app.worker``) calls ``run_next_job()`` in a loop. It claims one due
   job with ``SELECT … FOR UPDATE SKIP LOCKED`` (so several workers never take the same job),
   runs its handler, and marks it ``done`` in the same transaction as the handler's own
   database work.
3. If the handler fails, everything it did is rolled back and the job is retried later with a
   growing delay. ``PermanentJobError`` (or too many attempts) makes the job ``dead``.

Handlers are plain functions registered by kind (e.g. ``"quote.email"``). They run without a
signed-in user, so they must scope every query to ``job.tenant_id`` themselves, and they must
be safe to run twice (a worker can crash after sending an e-mail but before committing).

Payloads hold IDs only - never personal data, secrets or tokens.
"""

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.core.models import Base, TenantOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

logger = logging.getLogger(__name__)

JOB_STATUSES = ("pending", "running", "done", "dead")
# Delay before attempt 2, 3, 4, … (the last value repeats).
RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
)
# A job still "running" after this long belongs to a worker that died; it is taken again.
STALE_AFTER = timedelta(minutes=15)
_KIND_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*$"


class OutboxJob(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {JOB_STATUSES}", name="status_allowed"),
        CheckConstraint(f"kind ~ '{_KIND_PATTERN}'", name="kind_format"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # The worker's "next due job" query reads only unfinished jobs.
        Index(
            "ix_outbox_jobs_due",
            "run_after",
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_outbox_jobs_tenant_id_kind_created_at", "tenant_id", "kind", "created_at"),
    )

    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Short, safe description of the last failure (exception type + safe text, no personal data).
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)


class PermanentJobError(Exception):
    """Raise from a handler when retrying can't help (e.g. the record no longer exists).
    The message is stored in ``last_error``, so it must not contain personal data."""


@dataclass(frozen=True)
class Job:
    """What a handler receives (a plain copy, not the database row)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    payload: Mapping[str, Any]
    attempt: int  # 1 on the first run


# A handler gets the worker's session (its database work commits together with "done") and
# the job; services such as the file store or mailer come from the worker via closures.
JobHandler = Callable[[Session, Job], None]
# Called once when a job gives up for good, in the same transaction that marks it "dead",
# with the stored (safe) error text - e.g. to note "e-mail could not be sent" in a history.
DeadJobHandler = Callable[[Session, Job, str], None]


def _check_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("payload keys must be strings")
            _check_payload(item)
    elif isinstance(value, list):
        for item in value:
            _check_payload(item)
    elif not (value is None or isinstance(value, (str, int, float, bool))):
        raise TypeError("payload values must be JSON types (convert UUIDs to str)")


def enqueue(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any],
    run_after: datetime | None = None,
) -> OutboxJob:
    """Add a job in the caller's transaction (it exists only if the caller commits)."""
    _check_payload(payload)
    # The id is set here (not at flush), so callers can use it at once.
    job = OutboxJob(id=uuid.uuid4(), tenant_id=tenant_id, kind=kind, payload=payload)
    if run_after is not None:
        job.run_after = run_after
    session.add(job)
    return job


def retry_delay(attempt: int) -> timedelta:
    """Delay after failed attempt number ``attempt`` (1-based)."""
    return RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)) - 1]


def latest_job_status(
    session: Session, tenant_id: uuid.UUID, kind: str, ref_key: str, ref_value: str
) -> str | None:
    """Status of the newest job of this kind whose payload has ``ref_key == ref_value``
    (e.g. the last e-mail job of one quote), or None if there was none."""
    return session.scalar(
        select(OutboxJob.status)
        .where(
            OutboxJob.tenant_id == tenant_id,
            OutboxJob.kind == kind,
            OutboxJob.payload[ref_key].astext == ref_value,
        )
        # Unfinished work first ("still on its way" wins), then the newest. Jobs created in one
        # transaction share created_at, so finished_at breaks the tie.
        .order_by(
            OutboxJob.finished_at.is_(None).desc(),
            OutboxJob.created_at.desc(),
            OutboxJob.finished_at.desc(),
        )
        .limit(1)
    )


def _safe_error(exc: BaseException) -> str:
    # Only our own PermanentJobError messages are written by us and known to be safe; other
    # exception texts may echo data (e.g. an e-mail address), so only their type is kept.
    if isinstance(exc, PermanentJobError):
        return f"PermanentJobError: {exc}"[:500]
    return type(exc).__name__[:500]


def _claim(session_factory: sessionmaker[Session], now: datetime) -> Job | None:
    with session_factory() as session, session.begin():
        row = session.scalars(
            select(OutboxJob)
            .where(
                or_(
                    (OutboxJob.status == "pending") & (OutboxJob.run_after <= now),
                    (OutboxJob.status == "running") & (OutboxJob.locked_at < now - STALE_AFTER),
                )
            )
            .order_by(OutboxJob.run_after)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if row is None:
            return None
        row.status = "running"
        row.attempts += 1
        row.locked_at = now
        return Job(row.id, row.tenant_id, row.kind, dict(row.payload), row.attempts)


def run_next_job(
    session_factory: sessionmaker[Session],
    handlers: Mapping[str, JobHandler],
    *,
    max_attempts: int,
    permanent_errors: tuple[type[BaseException], ...] = (),
    dead_handlers: Mapping[str, DeadJobHandler] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Job | None:
    """Claim and run one due job. Returns it, or None when nothing is due.

    ``permanent_errors``: extra exception types that make a job ``dead`` at once
    (e.g. a mail server refusing a recipient).
    """
    job = _claim(session_factory, now())
    if job is None:
        return None
    handler = handlers.get(job.kind)
    try:
        if handler is None:
            raise PermanentJobError(f"no handler for kind {job.kind!r}")
        with session_factory() as session, session.begin():
            handler(session, job)
            session.execute(
                update(OutboxJob)
                .where(OutboxJob.id == job.id)
                .values(status="done", finished_at=now(), locked_at=None, last_error=None)
            )
        logger.info("job done", extra={"job_kind": job.kind, "attempt": job.attempt})
    except Exception as exc:  # noqa: BLE001 - any failure is recorded and retried
        permanent = isinstance(exc, (PermanentJobError, *permanent_errors))
        dead = permanent or job.attempt >= max_attempts
        values: dict[str, Any] = {"locked_at": None, "last_error": _safe_error(exc)}
        if dead:
            values |= {"status": "dead", "finished_at": now()}
        else:
            values |= {"status": "pending", "run_after": now() + retry_delay(job.attempt)}
        with session_factory() as session, session.begin():
            session.execute(update(OutboxJob).where(OutboxJob.id == job.id).values(**values))
            on_dead = (dead_handlers or {}).get(job.kind) if dead else None
            if on_dead is not None:
                try:
                    with session.begin_nested():  # a failing hook must not keep the job alive
                        on_dead(session, job, values["last_error"])
                except Exception:  # noqa: BLE001
                    logger.exception("dead-job handler failed", extra={"job_kind": job.kind})
        logger.warning(
            "job failed",
            extra={
                "job_kind": job.kind,
                "attempt": job.attempt,
                "dead": dead,
                "error": type(exc).__name__,
            },
        )
    return job
