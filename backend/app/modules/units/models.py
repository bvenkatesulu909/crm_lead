"""Projects and the units (flats, villas, plots, shops) inside them (ADR 0040, RP1).

A project is a development a seller sells from; a unit is one thing a buyer can reserve. The
reservation rules (ADR 0040, later steps) hold a unit for one buyer at a time, so the unit's
status lives here and only this module changes it.

Statuses: ``available`` and ``blocked`` are set by staff; ``reserved`` and ``sold`` belong to the
reservation steps (RP2 onwards) and no staff action can set them. Prices are rupees in ``NUMERIC``
(never a float).
"""

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)

UNIT_TYPES = ("apartment", "villa", "plot", "commercial")
UNIT_STATUSES = ("available", "blocked", "reserved", "sold")
# What a person may set by hand; the other two belong to the reservation steps.
MANUAL_STATUSES = ("available", "blocked")


class PropertyProject(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "property_projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="name_length"),
        Index(
            "uq_property_projects_tenant_id_lower_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    rera_number: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class PropertyUnit(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "property_units"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["property_projects.tenant_id", "property_projects.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"unit_type IN {UNIT_TYPES}", name="type_allowed"),
        CheckConstraint(f"status IN {UNIT_STATUSES}", name="status_allowed"),
        CheckConstraint("price >= 0", name="price_not_negative"),
        CheckConstraint("area_sqft IS NULL OR area_sqft > 0", name="area_positive"),
        CheckConstraint("char_length(unit_code) BETWEEN 1 AND 40", name="code_length"),
        Index(
            "uq_property_units_project_lower_code",
            "tenant_id",
            "project_id",
            text("lower(unit_code)"),
            unique=True,
        ),
        Index("ix_property_units_tenant_id_status", "tenant_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    unit_code: Mapped[str] = mapped_column(String(40))
    unit_type: Mapped[str] = mapped_column(String(20))
    area_sqft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'available'"))
