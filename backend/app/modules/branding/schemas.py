"""Request and response shapes of the branding API (ADR 0032). The tenant, the person and the logo
bytes are never part of a JSON body."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.branding import rules


class BrandingRead(BaseModel):
    primary_color: str = Field(description="Six hex digits, lower case, no #.")
    about_text: str
    terms_text: str
    contact_line: str
    footer_line: str
    has_logo: bool
    logo_width: int | None
    logo_height: int | None
    version: int = Field(description="0 while the organisation still uses the defaults.")
    updated_at: datetime | None
    cleaned_fields: list[str] = Field(
        default_factory=list,
        description="Fields where something (a link, markup, hidden characters) was taken out.",
    )


class BrandingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0, description="The version you read (0 for the defaults).")
    primary_color: str = Field(max_length=10)
    about_text: str = Field(max_length=rules.LIMITS["about_text"] * 2)
    terms_text: str = Field(max_length=rules.LIMITS["terms_text"] * 2)
    contact_line: str = Field(max_length=rules.LIMITS["contact_line"] * 2)
    footer_line: str = Field(max_length=rules.LIMITS["footer_line"] * 2)
