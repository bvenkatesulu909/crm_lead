"""Public interface of the communications module. Other modules import only from here."""

import uuid

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.mail import Mailer
from app.core.outbox import DeadJobHandler, Job, JobHandler, PermanentJobError
from app.modules.communications import service

EMAIL_JOB = service.EMAIL_JOB

__all__ = ["EMAIL_JOB", "email_failed_handler", "email_job_handler", "message_brief"]


def _message_id(job: Job) -> uuid.UUID:
    try:
        return uuid.UUID(str(job.payload["message_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("payload without a valid message_id") from exc


def email_job_handler(mailer: Mailer) -> JobHandler:
    """Worker handler for "communication.email": sends one queued e-mail."""

    def handle(session: Session, job: Job) -> None:
        service.run_send_job(session, mailer, tenant_id=job.tenant_id, message_id=_message_id(job))

    return handle


def email_failed_handler() -> DeadJobHandler:
    """Marks the e-mail failed and tells its sender, once the job has given up."""

    def handle(session: Session, job: Job, error: str) -> None:
        service.send_failed(session, job.tenant_id, _message_id(job), error)

    return handle


def message_brief(
    session: Session, principal: Principal, message_id: uuid.UUID
) -> tuple[str, str] | None:
    """(subject, link) of an e-mail this principal may see (for notifications), else None."""
    return service.message_brief(session, principal, message_id)
