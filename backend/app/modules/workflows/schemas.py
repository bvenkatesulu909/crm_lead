"""Request and response shapes for workflow rules."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.validation import Text100


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleCreate(_Input):
    name: Text100
    is_active: bool = True
    trigger: str = Field(max_length=50)
    days: int | None = Field(default=None, description="Schedules only: N days.")
    # Checked against the catalogue by the service (readable messages, 422 invalid_rule).
    conditions: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    actions: list[dict[str, Any]] = Field(max_length=20)


class RuleUpdate(RuleCreate):
    version: int = Field(ge=1)


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_active: bool
    trigger: str
    days: int | None
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    version: int


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str = ""
    record_type: str
    record_id: uuid.UUID
    record_label: str
    status: str
    message: str | None
    created_at: datetime


class FieldOut(BaseModel):
    key: str
    label: str
    type: str
    options: list[str]


class TriggerOut(BaseModel):
    key: str
    label: str
    kind: str
    record_type: str
    days_label: str | None
    fields: list[FieldOut]
    field_updates: list[FieldOut]


class Catalogue(BaseModel):
    triggers: list[TriggerOut]
    operators: dict[str, list[str]]
    roles: list[str]
    max_conditions: int
    max_actions: int
