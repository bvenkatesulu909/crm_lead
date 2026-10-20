"""Public interface of the knowledge module: the outbox job handler (RAG R1)."""

import uuid

from sqlalchemy.orm import Session

from app.core.outbox import Job, JobHandler
from app.core.storage import FileStore
from app.modules.knowledge import service

JOB_KIND = service.JOB_KIND


def ingest_handler(store: FileStore) -> JobHandler:
    """Worker handler factory: bytes come from the file store, the DB session from the worker."""

    def handler(session: Session, job: Job) -> None:
        document_id = uuid.UUID(str(job.payload["document_id"]))
        service.ingest_document(session, store, tenant_id=job.tenant_id, document_id=document_id)

    return handler
