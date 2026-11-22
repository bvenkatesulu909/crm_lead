"""Request and response shapes for projects and units.

Input bodies accept only the listed fields: the tenant and the statuses ``reserved`` / ``sold``
are never the client's to set."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

UnitType = Literal["apartment", "villa", "plot", "commercial"]
# Only these two can be set by a person (ADR 0040: the others come from the reservation steps).
ManualStatus = Literal["available", "blocked"]
UnitStatus = Literal["available", "blocked", "reserved", "sold"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ReraNumber = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9/\-]+$"
    ),
]
UnitCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._/\-]+$"
    ),
]
# Rupees with paise; the ceiling keeps a typo from becoming an absurd price.
Price = Annotated[Decimal, Field(ge=0, le=10_000_000_000, decimal_places=2, max_digits=14)]
Area = Annotated[Decimal, Field(gt=0, le=10_000_000, decimal_places=2, max_digits=10)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(_Input):
    name: Name
    location: Location | None = None
    rera_number: ReraNumber | None = None


class ProjectUpdate(_Input):
    version: int = Field(ge=1)
    name: Name | None = None
    location: Location | None = None
    rera_number: ReraNumber | None = None
    is_active: bool | None = Field(default=None, description="Inactive projects take no new units.")

    @model_validator(mode="after")
    def _check(self) -> "ProjectUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("name", "is_active"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: str | None
    rera_number: str | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    items: list[ProjectRead]
    total: int
    limit: int
    offset: int


class UnitCreate(_Input):
    project_id: uuid.UUID
    unit_code: UnitCode
    unit_type: UnitType
    price: Price
    area_sqft: Area | None = None


class UnitUpdate(_Input):
    version: int = Field(ge=1)
    unit_code: UnitCode | None = None
    unit_type: UnitType | None = None
    price: Price | None = None
    area_sqft: Area | None = None
    status: ManualStatus | None = Field(
        default=None, description="Staff can block or release a unit; reservations do the rest."
    )

    @model_validator(mode="after")
    def _check(self) -> "UnitUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("unit_code", "unit_type", "price", "status"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class UnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    unit_code: str
    unit_type: str
    area_sqft: Decimal | None
    price: Decimal
    currency: str = "INR"
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class UnitPage(BaseModel):
    items: list[UnitRead]
    total: int
    limit: int
    offset: int
