"""Response shapes for documents. Uploads are multipart forms (see router.py)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class UploadStart(BaseModel):
    """What a browser says before it sends a file straight to the store (ADR 0025). Nothing here
    is trusted beyond its shape: the record, the name, the size and the type are all checked."""

    model_config = ConfigDict(extra="forbid")

    record_type: UploadRecordType
    record_id: uuid.UUID
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    customer_visible: bool = False
    description: str | None = Field(default=None, max_length=500)


class UploadTicket(BaseModel):
    """Where and how to send the file: POST every field in ``fields`` to ``url``, in order, with
    the file last as the field ``file``; then call ``finish`` with ``upload_id``."""

    upload_id: uuid.UUID
    url: str
    fields: dict[str, str]
    expires_at: datetime
    max_bytes: int


class DownloadLinkRead(BaseModel):
    """Open ``url`` within a minute: it fetches the file straight from the file store."""

    url: str
    file_name: str
    expires_at: datetime
