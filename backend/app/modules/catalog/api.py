"""Public interface of the catalogue module (used by quotes for governed pricing)."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.models import PriceBook, PriceBookEntry, Product

__all__ = ["BookInfo", "PriceInfo", "price_book_info", "prices_for"]


@dataclass(frozen=True)
class BookInfo:
    id: uuid.UUID
    name: str
    currency: str
    is_active: bool


@dataclass(frozen=True)
class PriceInfo:
    product_id: uuid.UUID
    sku: str
    name: str
    unit: str
    tax_rate: Decimal
    unit_price: Decimal
    product_active: bool


def price_book_info(session: Session, tenant_id: uuid.UUID, book_id: uuid.UUID) -> BookInfo | None:
    book = session.scalars(
        select(PriceBook).where(PriceBook.tenant_id == tenant_id, PriceBook.id == book_id)
    ).one_or_none()
    if book is None:
        return None
    return BookInfo(book.id, book.name, book.currency, book.is_active)


def prices_for(
    session: Session, tenant_id: uuid.UUID, book_id: uuid.UUID, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PriceInfo]:
    """The current price of each product in the book (missing products are left out)."""
    if not product_ids:
        return {}
    rows = session.execute(
        select(PriceBookEntry.unit_price, Product)
        .join(
            Product,
            (Product.tenant_id == PriceBookEntry.tenant_id)
            & (Product.id == PriceBookEntry.product_id),
        )
        .where(
            PriceBookEntry.tenant_id == tenant_id,
            PriceBookEntry.price_book_id == book_id,
            PriceBookEntry.product_id.in_(product_ids),
        )
    ).all()
    return {
        product.id: PriceInfo(
            product.id, product.sku, product.name, product.unit, product.tax_rate, price,
            product.is_active,
        )
        for price, product in rows
    }  # fmt: skip
