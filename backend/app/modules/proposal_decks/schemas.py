"""Response shapes of the proposal deck API (ADR 0032). Requests carry no body: the quote is in the
path and everything else is decided by the server."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DeckStatusRead(BaseModel):
    status: Literal["none", "queued", "ready", "failed", "not_available"]
    reason: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None
    refresh_failed: bool = False


class DeckLinkRead(BaseModel):
    """Open ``url`` within a minute: it fetches the PDF straight from the file store."""

    url: str
    file_name: str
    expires_at: datetime
