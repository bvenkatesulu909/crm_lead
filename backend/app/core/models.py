"""Shared building blocks for database models.

Every business table inherits from ``Base`` and usually from these mixins:

- ``UUIDPrimaryKeyMixin``  random, non-guessable ``id`` (UUID).
- ``TimestampMixin``       ``created_at`` / ``updated_at`` in UTC, set by the database.
- ``TenantOwnedMixin``     ``tenant_id``: which tenant (customer company of the CRM) owns the row.
- ``SoftDeleteMixin``      ``deleted_at`` instead of physically deleting business records.
- ``VersionedMixin``       ``version`` counter for optimistic locking (detects lost updates).

Relationships between tenant-owned tables use *composite* foreign keys
``(tenant_id, other_id) -> other_table(tenant_id, id)``. The database itself then refuses
to link, for example, a contact of tenant A to an account of tenant B.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Predictable constraint names. Alembic needs names to be able to drop or change
# constraints later, and readable names make database errors easier to understand.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TenantOwnedMixin:
    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        # RESTRICT: a tenant that still owns data can never be deleted by accident.
        return mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


class VersionedMixin:
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:
        # SQLAlchemy adds "WHERE version = <old>" to every UPDATE and raises
        # StaleDataError if another request changed the row in the meantime.
        return {"version_id_col": cls.__table__.c.version}  # type: ignore[attr-defined]
