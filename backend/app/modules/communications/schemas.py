"""Request and response shapes for the Communication Center (ADR 0012).

The client chooses WHO (a lead or a contact, by ID) and WHAT (subject and text). The address,
the sender, the status and the times are server-controlled and can't be sent: unknown fields are
refused, so ``{"to": "someone@else"}`` is a 422, not an ignored field.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.communications.models import MESSAGE_BODY_MAX, TEMPLATE_BODY_MAX

Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# The text is kept exactly as written (line breaks and indentation matter in an e-mail).
Body = Annotated[str, StringConstraints(min_length=1, max_length=MESSAGE_BODY_MAX)]
TemplateName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
TemplateBody = Annotated[str, StringConstraints(min_length=1, max_length=TEMPLATE_BODY_MAX)]


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


# --- templates (step CC3) -------------------------------------------------------------------


def _not_blank(text: str | None) -> None:
    if text is not None and not text.strip():
        raise ValueError("the text can't be empty")


class TemplateCreate(_Input):
    name: TemplateName
    subject: Subject = Field(description="May use placeholders, e.g. {{recipient.first_name}}.")
    body: TemplateBody = Field(description="Plain text with placeholders from the fixed list.")

    @model_validator(mode="after")
    def _check(self) -> "TemplateCreate":
        _not_blank(self.body)
        return self


class TemplateUpdate(_Input):
    version: int = Field(ge=1)
    name: TemplateName | None = None
    subject: Subject | None = None
    body: TemplateBody | None = None
    is_active: bool | None = Field(
        default=None, description="Deactivated templates are hidden from agents."
    )

    @model_validator(mode="after")
    def _check(self) -> "TemplateUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for field in self.model_fields_set - {"version"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be removed")
        _not_blank(self.body)
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    subject: str
    body: str
    is_active: bool
    version: int
    created_by_user_id: uuid.UUID | None
    updated_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TemplatePreviewRequest(_Input):
    lead_id: uuid.UUID | None = Field(default=None, description="Fill in this lead, or…")
    contact_id: uuid.UUID | None = Field(
        default=None, description="…this contact. Neither: sample values."
    )

    @model_validator(mode="after")
    def _check(self) -> "TemplatePreviewRequest":
        if self.lead_id is not None and self.contact_id is not None:
            raise ValueError("preview for one lead or one contact, not both")
        return self


class TemplatePreview(BaseModel):
    subject: str
    body: str
    missing: list[str] = Field(description="Placeholders that had no value (left empty).")


class PlaceholderRead(BaseModel):
    name: str
    description: str
