"""Public interface of the web check module. Other modules import only from here."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.outbox import Job, JobHandler
from app.core.webfetch import HostLimiter, Resolver, Transport
from app.modules.webcheck import company_details, service

CHECK_JOB = service.CHECK_JOB
COMPANY_JOB = company_details.COMPANY_JOB
delete_expired = service.delete_expired
evidence_summary = service.evidence_summary
request_check = service.request_check
offered_sources = service.offered_sources

__all__ = [
    "CHECK_JOB",
    "COMPANY_JOB",
    "company_job_handler",
    "check_job_handler",
    "delete_expired",
    "evidence_summary",
    "offered_sources",
    "request_check",
]


def check_job_handler(
    settings: Settings,
    *,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
) -> JobHandler:
    """Worker handler for "webcheck.run". One limiter is shared by every run of this worker, so
    the one-request-a-second rule holds across checks, not just inside one. ``resolver`` and
    ``transport`` replace the network for tests and evaluations; the worker passes neither."""
    limiter = HostLimiter()

    def handle(session: Session, job: Job) -> None:
        service.run_check(
            session,
            job,
            settings=settings,
            limiter=limiter,
            resolver=resolver,
            transport=transport,
        )

    return handle


def company_job_handler(
    settings: Settings,
    *,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
) -> JobHandler:
    """Worker handler for "webcheck.company_details" (ADR 0026). Its own limiter: company sites
    are many hosts, each still asked at most once a second."""
    limiter = HostLimiter()

    def handle(session: Session, job: Job) -> None:
        company_details.run_lookup(
            session,
            job,
            settings=settings,
            limiter=limiter,
            resolver=resolver,
            transport=transport,
        )

    return handle
