"""Request and response shapes for notifications."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    title: str
    link: str
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    unread: int = Field(description="Unread notifications in total (not only on this page).")


class PreferenceRead(BaseModel):
    type: str
    label: str
    email: bool


class PreferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(max_length=50)
    email: bool


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PreferenceItem] = Field(max_length=50)
