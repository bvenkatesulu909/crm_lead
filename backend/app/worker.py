"""Background worker: runs outbox jobs (ADR 0005).

Run locally (from the backend folder, virtual environment active, in its own CMD window):

    python -m app.worker            keep running; Ctrl+C stops after the current job
    python -m app.worker --once     run every job that is due now, then exit

It uses the same code, settings and database as the API, but no HTTP server.
"""

import argparse
import logging
import signal
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import FrameType

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.ai.embeddings import build_embedder
from app.core.config import Settings, get_settings
from app.core.db import bind_tenant, create_db_engine, create_session_factory
from app.core.events import EventHandler, dispatcher
from app.core.heartbeat import record_heartbeat
from app.core.logging import configure_logging
from app.core.mail import Mailer, MailRejectedError, build_mailer
from app.core.outbox import DeadJobHandler, JobHandler, run_next_job
from app.core.storage import FileStore, build_file_store
from app.modules.activities import api as activities_api
from app.modules.contracts import api as contracts_api
from app.modules.identity.models import Tenant
from app.modules.knowledge import api as knowledge_api
from app.modules.notifications import api as notifications_api
from app.modules.quotes import api as quotes_api
from app.modules.workflows import api as workflows_api

logger = logging.getLogger("app.worker")
# Schedule triggers of workflow rules are checked about once a minute, not every loop.
WORKFLOW_SCHEDULE_SECONDS = 60


@dataclass(frozen=True)
class WorkerServices:
    """What job handlers may use besides the database session."""

    settings: Settings
    file_store: FileStore
    mailer: Mailer


def job_handlers(services: WorkerServices) -> dict[str, JobHandler]:
    """Every job kind the worker knows. Modules provide handlers through their api.py."""
    return {
        knowledge_api.JOB_KIND: knowledge_api.ingest_handler(
            services.file_store, build_embedder(services.settings)
        ),
        quotes_api.PDF_JOB: quotes_api.pdf_job_handler(services.file_store),
        quotes_api.EMAIL_JOB: quotes_api.email_job_handler(
            services.file_store, services.mailer, services.settings.web_app_url
        ),
        notifications_api.EMAIL_JOB: notifications_api.email_job_handler(
            services.mailer, services.settings.web_app_url
        ),
        # Domain events (ADR 0006): every "event.<name>" job goes to its subscribers.
        **dispatcher(
            merge_subscribers(
                notifications_api.event_subscribers(),
                workflows_api.event_subscribers(services.settings.workflow_actions_per_hour),
            )
        ),
    }


def merge_subscribers(
    *groups: dict[str, list[EventHandler]],
) -> dict[str, list[EventHandler]]:
    """Several modules may subscribe to the same event; each gets it, in this order."""
    merged: dict[str, list[EventHandler]] = {}
    for group in groups:
        for name, handlers in group.items():
            merged.setdefault(name, []).extend(handlers)
    return merged


def run_schedules(
    session_factory: sessionmaker[Session],
    settings: Settings | None = None,
    *,
    include_workflows: bool = True,
) -> int:
    """Time-based work (ADR 0006): task reminders whose time has come and, when asked,
    workflow rules with a schedule trigger (the loop asks about once a minute)."""
    now = datetime.now(UTC)
    with session_factory() as session:
        tenant_ids = list(session.scalars(select(Tenant.id).where(Tenant.status == "active")).all())
    count = 0
    limit = settings.workflow_actions_per_hour if settings else 500
    for tenant_id in tenant_ids:
        # Each tenant's scheduled work runs in its own transaction with app.tenant_id set.
        with session_factory() as session, session.begin():
            bind_tenant(session, tenant_id)
            count += activities_api.publish_due_reminders(session, now, tenant_id=tenant_id)
        if include_workflows:
            # Contract expiry and renewal reminders: cheap, indexed and safe to repeat.
            with session_factory() as session, session.begin():
                bind_tenant(session, tenant_id)
                count += contracts_api.run_schedules(session, now, tenant_id=tenant_id)
            with session_factory() as session, session.begin():
                bind_tenant(session, tenant_id)
                count += workflows_api.run_schedules(
                    session, now, hourly_limit=limit, tenant_id=tenant_id
                )
    return count


def dead_job_handlers() -> dict[str, DeadJobHandler]:
    """What to do when a job gives up for good (e.g. note it in the record's history)."""
    return {quotes_api.EMAIL_JOB: quotes_api.email_failed_handler()}


def run_due_jobs(
    session_factory: sessionmaker[Session],
    handlers: Mapping[str, JobHandler],
    settings: Settings,
    stop: threading.Event | None = None,
) -> int:
    """Run jobs until none is due (or ``stop`` is set). Returns how many ran."""
    count = 0
    while not (stop and stop.is_set()):
        job = run_next_job(
            session_factory,
            handlers,
            max_attempts=settings.worker_max_attempts,
            permanent_errors=(MailRejectedError,),
            dead_handlers=dead_job_handlers(),
        )
        if job is None:
            break
        count += 1
    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker", description=__doc__)
    parser.add_argument("--once", action="store_true", help="run due jobs, then exit")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    services = WorkerServices(settings, build_file_store(settings), build_mailer(settings))
    handlers = job_handlers(services)

    stop = threading.Event()

    def _request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("stopping after the current job", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    logger.info("worker started", extra={"job_kinds": sorted(handlers), "once": args.once})
    try:
        if args.once:
            record_heartbeat(session_factory)
            run_schedules(session_factory, settings)
            knowledge_api.run_maintenance(
                session_factory, embedding_model=settings.embeddings_model
            )
            ran = run_due_jobs(session_factory, handlers, settings, stop)
            logger.info("worker finished", extra={"jobs_run": ran})
            return
        last_rules = 0.0
        while not stop.is_set():
            try:
                record_heartbeat(session_factory)
                due = time.monotonic() - last_rules >= WORKFLOW_SCHEDULE_SECONDS
                run_schedules(session_factory, settings, include_workflows=due)
                try:
                    knowledge_api.run_maintenance(
                        session_factory, embedding_model=settings.embeddings_model
                    )
                except Exception:  # noqa: BLE001 - maintenance must never stop the worker
                    logger.exception("knowledge maintenance failed")
                if due:
                    last_rules = time.monotonic()
                run_due_jobs(session_factory, handlers, settings, stop)
            except Exception:  # noqa: BLE001 - e.g. database restarting; keep the worker alive
                logger.exception("worker loop error; retrying shortly")
            stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
