"""Public interface of the web check module. Other modules import only from here."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.outbox import Job, JobHandler
from app.core.webfetch import HostLimiter
from app.modules.webcheck import service

CHECK_JOB = service.CHECK_JOB
delete_expired = service.delete_expired
request_check = service.request_check
offered_sources = service.offered_sources

__all__ = [
    "CHECK_JOB",
    "check_job_handler",
    "delete_expired",
    "offered_sources",
    "request_check",
]


def check_job_handler(settings: Settings) -> JobHandler:
    """Worker handler for "webcheck.run". One limiter is shared by every run of this worker, so
    the one-request-a-second rule holds across checks, not just inside one."""
    limiter = HostLimiter()

    def handle(session: Session, job: Job) -> None:
        service.run_check(session, job, settings=settings, limiter=limiter)

    return handle
