"""Response shapes for documents. Uploads are multipart forms (see router.py)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Records people can attach documents to (quote PDFs are made by the system).
UploadRecordType = Literal["account", "opportunity"]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    group_id: uuid.UUID
    version_no: int
    record_type: str
    record_id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    description: str | None
    customer_visible: bool
    created_at: datetime
    created_by_name: str | None = None
    versions: int = 1


class DocumentList(BaseModel):
    items: list[DocumentRead]


class PortalDocumentRead(BaseModel):
    """What a customer sees: no uploader, no internal description."""

    id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    version_no: int
    created_at: datetime


class PortalDocumentList(BaseModel):
    items: list[PortalDocumentRead]
