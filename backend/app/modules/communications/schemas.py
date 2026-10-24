"""Request and response shapes for the Communication Center (ADR 0012).

The client chooses WHO (a lead or a contact, by ID) and WHAT (subject and text). The address,
the sender, the status and the times are server-controlled and can't be sent: unknown fields are
refused, so ``{"to": "someone@else"}`` is a 422, not an ignored field.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.communications.models import MESSAGE_BODY_MAX

Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# The text is kept exactly as written (line breaks and indentation matter in an e-mail).
Body = Annotated[str, StringConstraints(min_length=1, max_length=MESSAGE_BODY_MAX)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailSend(_Input):
    lead_id: uuid.UUID | None = Field(default=None, description="Write to this lead, or…")
    contact_id: uuid.UUID | None = Field(default=None, description="…to this contact.")
    account_id: uuid.UUID | None = Field(
        default=None, description="File it under the contact's account (contacts only)."
    )
    opportunity_id: uuid.UUID | None = Field(
        default=None, description="Or under a deal of the contact's account (contacts only)."
    )
    subject: Subject
    body: Body
    template_id: uuid.UUID | None = Field(
        default=None, description="The template the text started from, if any."
    )

    @model_validator(mode="after")
    def _check(self) -> "EmailSend":
        if (self.lead_id is None) == (self.contact_id is None):
            raise ValueError("write to exactly one lead or one contact")
        if self.account_id is not None and self.opportunity_id is not None:
            raise ValueError("file the e-mail under one account or one deal, not both")
        if self.lead_id is not None and (self.account_id or self.opportunity_id):
            raise ValueError("an e-mail to a lead can't be filed under an account or deal")
        if not self.body.strip():
            raise ValueError("the text can't be empty")
        return self


class EmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: Literal["outbound", "inbound_logged"]
    status: Literal["queued", "sent", "failed", "logged"]
    lead_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    account_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    to_address: str
    subject: str
    body: str
    template_id: uuid.UUID | None
    sent_by_user_id: uuid.UUID
    sent_at: datetime | None
    error_code: str | None
    created_at: datetime
