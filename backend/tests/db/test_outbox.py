"""Outbox jobs and the worker loop (ADR 0005), against the real PostgreSQL test database."""

import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.mail import MailRejectedError
from app.core.outbox import (
    RETRY_DELAYS,
    STALE_AFTER,
    Job,
    JobHandler,
    OutboxJob,
    PermanentJobError,
    _claim,
    enqueue,
    retry_delay,
    run_next_job,
)
from app.modules.identity.models import Tenant
from app.worker import run_due_jobs
from tests.auth_helpers import TEST_ISSUER
from tests.db.conftest import session_factory_for

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def factory(db_connection: Connection) -> sessionmaker[Session]:
    return session_factory_for(db_connection)


@pytest.fixture
def tenant(db_session: Session) -> Tenant:
    tenant = Tenant(slug=f"outbox-{uuid.uuid4().hex[:10]}", name="Outbox test")
    db_session.add(tenant)
    db_session.commit()
    return tenant


def add_job(
    factory: sessionmaker[Session], tenant: Tenant, kind: str = "test.ping", **changes: object
) -> uuid.UUID:
    with factory() as session, session.begin():
        # Producers always enqueue inside a tenant-bound request or job (outbox_jobs has RLS).
        bind_tenant(session, tenant.id)
        job = enqueue(
            session,
            tenant_id=tenant.id,
            kind=kind,
            payload={"n": 1},
            run_after=NOW - timedelta(seconds=1),
        )
        for name, value in changes.items():
            setattr(job, name, value)
        session.flush()
        return job.id


def load(factory: sessionmaker[Session], job_id: uuid.UUID, tenant: Tenant) -> OutboxJob:
    with factory() as session:
        bind_tenant(session, tenant.id)
        job = session.get(OutboxJob, job_id)
        assert job is not None
        return job


def run(
    factory: sessionmaker[Session], handlers: dict[str, JobHandler], **kwargs: object
) -> Job | None:
    return run_next_job(factory, handlers, max_attempts=3, now=lambda: NOW, **kwargs)  # type: ignore[arg-type]


def test_a_job_exists_only_if_the_change_is_committed(factory, tenant) -> None:
    with factory() as session:
        session.begin()
        bind_tenant(session, tenant.id)
        enqueue(session, tenant_id=tenant.id, kind="test.ping", payload={})
        session.rollback()
    with factory() as session:
        bind_tenant(session, tenant.id)
        assert (
            session.scalars(select(OutboxJob).where(OutboxJob.tenant_id == tenant.id)).all() == []
        )


def test_payloads_hold_plain_values_only(factory, tenant) -> None:
    with factory() as session, pytest.raises(TypeError):
        enqueue(session, tenant_id=tenant.id, kind="test.ping", payload={"id": uuid.uuid4()})


def test_job_kinds_have_a_fixed_format(factory, tenant) -> None:
    with pytest.raises(Exception, match="kind_format"):
        add_job(factory, tenant, kind="Drop Table")


def test_handler_work_and_done_are_saved_together(factory, tenant, db_session) -> None:
    job_id = add_job(factory, tenant)
    seen: list[Job] = []

    def handler(session: Session, job: Job) -> None:
        seen.append(job)
        session.add(Tenant(slug=f"made-{job.id.hex[:10]}", name="Made by a job"))

    assert run(factory, {"test.ping": handler}).id == job_id  # type: ignore[union-attr]
    assert [(j.tenant_id, j.payload, j.attempt) for j in seen] == [(tenant.id, {"n": 1}, 1)]
    job = load(factory, job_id, tenant)
    assert (job.status, job.attempts, job.finished_at, job.last_error) == ("done", 1, NOW, None)
    assert db_session.scalar(select(Tenant).where(Tenant.slug == f"made-{job_id.hex[:10]}"))
    assert run(factory, {"test.ping": handler}) is None  # nothing left
    assert len(seen) == 1


def test_a_failed_job_is_rolled_back_and_retried_later(factory, tenant, db_session) -> None:
    job_id = add_job(factory, tenant)

    def handler(session: Session, job: Job) -> None:
        session.add(Tenant(slug=f"lost-{job.id.hex[:10]}", name="Rolled back"))
        session.flush()
        raise RuntimeError("customer@example.test is unreachable")  # personal data in text

    run(factory, {"test.ping": handler})
    job = load(factory, job_id, tenant)
    assert (job.status, job.attempts) == ("pending", 1)
    assert job.run_after == NOW + RETRY_DELAYS[0]
    assert job.last_error == "RuntimeError"  # the message is NOT stored
    assert db_session.scalar(select(Tenant).where(Tenant.slug == f"lost-{job_id.hex[:10]}")) is None
    assert run(factory, {"test.ping": handler}) is None  # not due again yet


def test_retry_delays_grow_and_then_stay() -> None:
    assert [retry_delay(n) for n in (1, 2, 3)] == list(RETRY_DELAYS[:3])
    assert retry_delay(99) == RETRY_DELAYS[-1]


def test_too_many_attempts_make_a_job_dead(factory, tenant) -> None:
    job_id = add_job(factory, tenant, attempts=2)  # the next try is attempt 3 of 3

    def handler(session: Session, job: Job) -> None:
        raise TimeoutError

    run(factory, {"test.ping": handler})
    job = load(factory, job_id, tenant)
    assert (job.status, job.attempts, job.finished_at) == ("dead", 3, NOW)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermanentJobError("quote no longer exists"), "PermanentJobError: quote no longer exists"),
        (MailRejectedError("refused x@example.test"), "MailRejectedError"),
    ],
)
def test_permanent_errors_stop_at_once(factory, tenant, error, expected) -> None:
    job_id = add_job(factory, tenant)

    def handler(session: Session, job: Job) -> None:
        raise error

    run(factory, {"test.ping": handler}, permanent_errors=(MailRejectedError,))
    job = load(factory, job_id, tenant)
    assert (job.status, job.attempts, job.last_error) == ("dead", 1, expected)


def test_unknown_kinds_are_dead_not_retried_forever(factory, tenant) -> None:
    job_id = add_job(factory, tenant, kind="test.unknown")
    run(factory, {})
    assert load(factory, job_id, tenant).status == "dead"


def test_future_and_finished_jobs_are_left_alone(factory, tenant) -> None:
    add_job(factory, tenant, run_after=NOW + timedelta(minutes=1))
    add_job(factory, tenant, status="done")
    add_job(factory, tenant, status="dead")
    assert run(factory, {"test.ping": lambda s, j: None}) is None


def test_a_job_of_a_crashed_worker_is_taken_again(factory, tenant) -> None:
    fresh = add_job(factory, tenant, status="running", locked_at=NOW - timedelta(minutes=1))
    stale = add_job(factory, tenant, status="running", locked_at=NOW - STALE_AFTER - timedelta(1))
    ran = run(factory, {"test.ping": lambda s, j: None})
    assert ran is not None and ran.id == stale
    assert load(factory, fresh, tenant).status == "running"  # still owned by a live worker


def test_the_worker_runs_every_due_job_in_order(factory, tenant) -> None:
    real_now = datetime.now(UTC)  # run_due_jobs uses the real clock
    first = add_job(factory, tenant, run_after=real_now - timedelta(minutes=2))
    second = add_job(factory, tenant, run_after=real_now - timedelta(minutes=1))
    order: list[uuid.UUID] = []
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@127.0.0.1:1/none",
        oidc_issuer=TEST_ISSUER,
    )
    assert run_due_jobs(factory, {"test.ping": lambda s, j: order.append(j.id)}, settings) == 2
    assert order == [first, second]


# --- two workers at the same time: needs real, committed transactions ----------------------


@pytest.fixture
def committed_jobs(owner_engine: Engine) -> Iterator[tuple[uuid.UUID, list[uuid.UUID]]]:
    # Setup as crm_owner (BYPASSRLS); the workers below still run as the restricted app role.
    tenant_id = uuid.uuid4()
    with Session(owner_engine) as session:
        session.add(Tenant(id=tenant_id, slug=f"outbox-race-{tenant_id.hex[:8]}", name="Race"))
        session.flush()
        jobs = [
            enqueue(session, tenant_id=tenant_id, kind="test.ping", payload={}, run_after=NOW)
            for _ in range(2)
        ]
        session.commit()
        ids = [job.id for job in jobs]
    try:
        yield tenant_id, ids
    finally:
        with owner_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM outbox_jobs WHERE tenant_id = :t"), {"t": tenant_id}
            )
            connection.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


def test_two_workers_never_take_the_same_job(app_engine: Engine, committed_jobs) -> None:
    tenant_id, job_ids = committed_jobs
    factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    holding = threading.Event()
    release = threading.Event()
    taken: list[uuid.UUID] = []

    def slow_worker() -> None:
        # Holds the row lock on one job, like a worker in the middle of claiming it.
        with factory() as session, session.begin():
            bind_tenant(session, tenant_id)
            row = session.scalars(
                select(OutboxJob)
                .where(OutboxJob.id.in_(job_ids))
                .order_by(OutboxJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).one()
            taken.append(row.id)
            holding.set()
            release.wait(10)

    thread = threading.Thread(target=slow_worker)
    thread.start()
    try:
        assert holding.wait(10)
        claimed = _claim(factory, NOW + timedelta(seconds=1))  # the second worker
        assert claimed is not None
        assert claimed.id in job_ids and claimed.id != taken[0]
    finally:
        release.set()
        thread.join()
