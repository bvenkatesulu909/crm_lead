"""Public interface of the notifications module (used by the worker)."""

import uuid

from sqlalchemy.orm import Session

from app.core.events import Event, EventHandler
from app.core.mail import Mailer
from app.core.outbox import Job, JobHandler, PermanentJobError
from app.modules.notifications import service

__all__ = ["EMAIL_JOB", "email_job_handler", "event_subscribers", "notify_users"]

EMAIL_JOB = service.EMAIL_JOB
notify_users = service.notify_users


def event_subscribers() -> dict[str, list[EventHandler]]:
    """{event name: [handler]} for every event that can notify someone."""

    def handle(session: Session, event: Event) -> None:
        service.on_event(session, event)

    return {name: [handle] for name in service.RULES}


def email_job_handler(mailer: Mailer, web_app_url: str) -> JobHandler:
    def handle(session: Session, job: Job) -> None:
        try:
            notification_id = uuid.UUID(str(job.payload["notification_id"]))
        except (KeyError, ValueError) as exc:
            raise PermanentJobError("payload without a valid notification_id") from exc
        service.send_email(session, mailer, job.tenant_id, notification_id, web_app_url)

    return handle
