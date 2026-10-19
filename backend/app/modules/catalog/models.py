"""Products, price books and their prices.

A price book is a list of prices in ONE currency (e.g. "Standard EUR", "Partner USD"). A
quote picks one price book; every quote line's price comes from that book, so sales reps
cannot invent prices - they can only give a discount, and big discounts need approval.
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
    Text,
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

PRODUCT_TYPES = ("product", "service", "subscription")


class Product(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "sku"),
        CheckConstraint(f"product_type IN {PRODUCT_TYPES}", name="type_allowed"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_range"),
        Index("ix_products_tenant_id_lower_name", "tenant_id", text("lower(name)")),
    )

    sku: Mapped[str] = mapped_column(String(64))  # the product code shown on documents
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str] = mapped_column(String(20), server_default=text("'product'"))
    unit: Mapped[str] = mapped_column(String(20), server_default=text("'each'"))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class PriceBook(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "price_books"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        # At most one default price book per currency.
        Index(
            "uq_price_books_one_default_per_currency",
            "tenant_id",
            "currency",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(String(500))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class PriceBookEntry(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    """The price of one product in one price book."""

    __tablename__ = "price_book_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "price_book_id", "product_id"),
        ForeignKeyConstraint(
            ["tenant_id", "price_book_id"],
            ["price_books.tenant_id", "price_books.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"], ["products.tenant_id", "products.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("unit_price >= 0", name="price_not_negative"),
    )

    price_book_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
