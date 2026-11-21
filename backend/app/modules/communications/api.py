"""Public interface of the communications module. Other modules import only from here."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import get_settings
from app.core.mail import Mailer
from app.core.outbox import DeadJobHandler, Job, JobHandler, PermanentJobError
from app.modules.communications import follow_up_rules, repository, service

EMAIL_JOB = service.EMAIL_JOB

__all__ = [
    "EMAIL_JOB",
    "email_failed_handler",
    "email_job_handler",
    "follow_up_policy",
    "follow_up_rules",
    "follow_up_problem",
    "inbound_logged_since",
    "render_follow_up",
    "message_brief",
    "queued_text",
    "send_follow_up",
]


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


def follow_up_problem(
    session: Session,
    tenant_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> str | None:
    """Why a follow-up draft to this lead or contact can't be proposed, or None (ADR 0036)."""
    return service.follow_up_problem(session, tenant_id, target_type, target_id, template_id)


def send_follow_up(
    session: Session,
    principal: Principal,
    *,
    target_type: str,
    target_id: uuid.UUID,
    subject: str,
    body: str,
    template_id: uuid.UUID | None,
) -> uuid.UUID:
    """Queue an approved follow-up through the normal e-mail path, as the approver (ADR 0036):
    the recipient, address, consent and hourly-limit checks and the audit all apply as for any
    other e-mail. Returns the message id."""
    return service.send_follow_up(
        session,
        principal,
        target_type=target_type,
        target_id=target_id,
        subject=subject,
        body=body,
        template_id=template_id,
        hourly_limit=get_settings().communication_emails_per_hour,
    )


def queued_text(
    session: Session, tenant_id: uuid.UUID, message_id: uuid.UUID
) -> tuple[str, str] | None:
    """(subject, text) of a stored message, for the approval's outcome check."""
    return service.stored_text(session, tenant_id, message_id)


def follow_up_policy(session: Session, tenant_id: uuid.UUID) -> follow_up_rules.Policy:
    """The organisation's follow-up settings in force (switched off when none was saved)."""
    return repository.current_follow_up_policy(session, tenant_id)


def inbound_logged_since(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID, since: datetime | None
) -> bool:
    return repository.inbound_logged_since(session, tenant_id, lead_id, since)


def render_follow_up(
    session: Session,
    automation: Principal,
    template_id: uuid.UUID,
    *,
    first_name: str | None,
    full_name: str,
    company: str | None,
    sender_name: str | None,
    sender_email: str | None,
) -> tuple[str, str] | None:
    return service.render_follow_up(
        session,
        automation,
        template_id,
        first_name=first_name,
        full_name=full_name,
        company=company,
        sender_name=sender_name,
        sender_email=sender_email,
    )


def message_brief(
    session: Session, principal: Principal, message_id: uuid.UUID
) -> tuple[str, str] | None:
    """(subject, link) of an e-mail this principal may see (for notifications), else None."""
    return service.message_brief(session, principal, message_id)
