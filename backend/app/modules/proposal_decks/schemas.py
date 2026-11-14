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


class SummaryDraftRead(BaseModel):
    """What asking the deck writer gave: a proposal waiting in the approval queue (nothing is
    drawn into a deck until a different person approves it), or a refusal by the safety check."""

    outcome: Literal["proposed", "blocked"]
    proposal_id: str | None = None
    proposal_link: str | None = None
    blocked_message: str | None = None


class DeckLinkRead(BaseModel):
    """Open ``url`` within a minute: it fetches the file (PDF or PowerPoint) from the file store."""

    url: str
    file_name: str
    expires_at: datetime
