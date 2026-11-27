"""Request and response bodies of /api/v1/saved-filters. Input bodies accept only the documented
fields: the owner, the organisation and the record type are never taken from the client."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SavedFilterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(
        description="The Accounts list's own filter parameters (q, status, segment, ...)."
    )
    shared: bool = False


class SavedFilterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    params: dict[str, Any] | None = None
    shared: bool | None = None


class SavedFilterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    record_type: Literal["account"]
    name: str
    params: dict[str, str]
    shared: bool
    owner_user_id: uuid.UUID
    mine: bool
    version: int
    created_at: datetime
    updated_at: datetime


class SavedFilterPage(BaseModel):
    items: list[SavedFilterRead]
