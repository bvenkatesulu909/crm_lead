"""Public interface of the photo enhancer module (ADR 0039). Other modules import only from here."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.outbox import DeadJobHandler, Job, JobHandler
from app.core.storage import FileStore
from app.modules.photo_enhancer import service

AGENT_KEY = service.AGENT_KEY
JOB_KIND = service.JOB_KIND

__all__ = ["AGENT_KEY", "JOB_KIND", "dead_job_handler", "job_handler"]


def job_handler(store: FileStore, settings: Settings) -> JobHandler:
    """Worker handler for "photo.enhance"."""

    def handle(session: Session, job: Job) -> None:
        service.process(session, job, store=store, settings=settings)

    return handle


def dead_job_handler() -> DeadJobHandler:
    return service.on_dead
