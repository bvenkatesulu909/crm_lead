"""Request and answer shapes of /api/v1/lead-agent (ADR 0022, step LA4)."""

import uuid

from pydantic import BaseModel, ConfigDict


class RunCreate(BaseModel):
    """Ask the lead agent to look at one lead. The person and the organisation come from the
    token; nothing else is accepted."""

    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID


class RunRead(BaseModel):
    outcome: str  # "proposed" | "no_suggestion" | "blocked"
    proposal_id: uuid.UUID | None
    # Where the person who approves sees the proposal; None when nothing was proposed.
    proposal_link: str | None
    # Why the safety check refused the suggestion, if it did (plain words, no model text).
    blocked_message: str | None
