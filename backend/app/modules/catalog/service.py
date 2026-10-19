"""Catalogue rules. Functions here never commit: the router commits once.

- Products and price books belong to one tenant; the whole tenant's staff may read them.
- Only managers and administrators (``catalog:manage``) change them; every price change is
  written to the audit log (governed pricing: who changed which price, from what, to what).
- Products are deactivated, never deleted, because old quotes and orders refer to them.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import diff, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.search import escape_like
from app.modules.catalog.models import PriceBook, PriceBookEntry, Product
from app.modules.catalog.schemas import (
    PriceBookCreate,
    PriceBookUpdate,
    PriceRead,
    ProductCreate,
    ProductUpdate,
)

_PRODUCT_FIELDS = ("sku", "name", "description", "product_type", "unit", "tax_rate", "is_active")


class ProductNotFoundError(NotFoundError):
    code = "product_not_found"

    def __init__(self) -> None:
        super().__init__("Product not found.")


class PriceBookNotFoundError(NotFoundError):
    code = "price_book_not_found"

    def __init__(self) -> None:
        super().__init__("Price book not found.")


class DuplicateError(ConflictError):
    code = "already_exists"


class VersionConflictError(ConflictError):
    code = "version_conflict"


def _tenant(principal: Principal, *, manage: bool = False) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can use the catalogue.")
    needed = Permission.CATALOG_MANAGE if manage else Permission.CATALOG_READ
    if not principal.has_permission(needed):
        raise ForbiddenError("Your role may not do this in the catalogue.")
    return principal.tenant_id


def _flush(session: Session, what: str) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(f"The {what} was changed by someone else. Reload it.") from exc
    except IntegrityError as exc:
        raise DuplicateError(f"A {what} with this name or code already exists.") from exc


def _check_version(current: int, sent: int, what: str) -> None:
    if current != sent:
        raise VersionConflictError(
            f"The {what} was changed by someone else (now version {current}). Reload it."
        )


def _taken(
    session: Session,
    model: type[Product] | type[PriceBook],
    tenant_id: uuid.UUID,
    column: str,
    value: str,
    except_id: uuid.UUID | None,
) -> bool:
    """Unique per tenant (checked first, so the user gets a clear 409, not a DB error)."""
    statement = select(model.id).where(
        model.tenant_id == tenant_id, func.lower(getattr(model, column)) == value.lower()
    )
    if except_id is not None:
        statement = statement.where(model.id != except_id)
    return session.scalar(statement.limit(1)) is not None


# --- products ----------------------------------------------------------------------------


def list_products(
    session: Session,
    principal: Principal,
    *,
    q: str | None,
    active: bool | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Product], int]:
    tenant_id = _tenant(principal)
    statement = select(Product).where(Product.tenant_id == tenant_id)
    if q:
        pattern = f"%{escape_like(q)}%"
        statement = statement.where(
            or_(Product.name.ilike(pattern, escape="\\"), Product.sku.ilike(pattern, escape="\\"))
        )
    if active is not None:
        statement = statement.where(Product.is_active.is_(active))
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(func.lower(Product.name), Product.id).limit(limit).offset(offset)
    ).all()
    return rows, total


def get_product(session: Session, principal: Principal, product_id: uuid.UUID) -> Product:
    tenant_id = _tenant(principal)
    product = session.scalars(
        select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
    ).one_or_none()
    if product is None:
        raise ProductNotFoundError()
    return product


def create_product(session: Session, principal: Principal, data: ProductCreate) -> Product:
    tenant_id = _tenant(principal, manage=True)
    if _taken(session, Product, tenant_id, "sku", data.sku, None):
        raise DuplicateError("Another product already uses this product code.")
    product = Product(tenant_id=tenant_id, **data.model_dump())
    session.add(product)
    _flush(session, "product")
    record_audit(
        session,
        principal,
        action="product.created",
        entity_type="product",
        entity_id=product.id,
        changes={"sku": product.sku, "name": product.name},
    )
    _flush(session, "product")
    session.refresh(product)
    return product


def update_product(
    session: Session, principal: Principal, product_id: uuid.UUID, data: ProductUpdate
) -> Product:
    _tenant(principal, manage=True)
    product = get_product(session, principal, product_id)
    _check_version(product.version, data.version, "product")
    if data.sku and _taken(session, Product, product.tenant_id, "sku", data.sku, product.id):
        raise DuplicateError("Another product already uses this product code.")
    before = {f: getattr(product, f) for f in _PRODUCT_FIELDS}
    for field, value in data.changes().items():
        setattr(product, field, value)
    changed = diff(before, {f: getattr(product, f) for f in _PRODUCT_FIELDS})
    if changed:
        record_audit(
            session,
            principal,
            action="product.updated",
            entity_type="product",
            entity_id=product.id,
            changes=changed,
        )
    _flush(session, "product")
    session.refresh(product)
    return product


# --- price books -------------------------------------------------------------------------


def list_price_books(
    session: Session, principal: Principal, *, active: bool | None
) -> Sequence[PriceBook]:
    tenant_id = _tenant(principal)
    statement = select(PriceBook).where(PriceBook.tenant_id == tenant_id)
    if active is not None:
        statement = statement.where(PriceBook.is_active.is_(active))
    return session.scalars(statement.order_by(PriceBook.currency, func.lower(PriceBook.name))).all()


def get_price_book(session: Session, principal: Principal, book_id: uuid.UUID) -> PriceBook:
    tenant_id = _tenant(principal)
    book = session.scalars(
        select(PriceBook).where(PriceBook.tenant_id == tenant_id, PriceBook.id == book_id)
    ).one_or_none()
    if book is None:
        raise PriceBookNotFoundError()
    return book


def _clear_other_defaults(session: Session, book: PriceBook) -> None:
    session.execute(
        update(PriceBook)
        .where(
            PriceBook.tenant_id == book.tenant_id,
            PriceBook.currency == book.currency,
            PriceBook.id != book.id,
            PriceBook.is_default.is_(True),
        )
        .values(is_default=False, version=PriceBook.version + 1)
        .execution_options(synchronize_session=False)
    )


def create_price_book(session: Session, principal: Principal, data: PriceBookCreate) -> PriceBook:
    tenant_id = _tenant(principal, manage=True)
    if _taken(session, PriceBook, tenant_id, "name", data.name, None):
        raise DuplicateError("Another price book already has this name.")
    book = PriceBook(tenant_id=tenant_id, id=uuid.uuid4(), **data.model_dump())
    if book.is_default:
        _clear_other_defaults(session, book)
    session.add(book)
    _flush(session, "price book")
    record_audit(
        session,
        principal,
        action="price_book.created",
        entity_type="price_book",
        entity_id=book.id,
        changes={"name": book.name, "currency": book.currency},
    )
    return book


def update_price_book(
    session: Session, principal: Principal, book_id: uuid.UUID, data: PriceBookUpdate
) -> PriceBook:
    _tenant(principal, manage=True)
    book = get_price_book(session, principal, book_id)
    _check_version(book.version, data.version, "price book")
    if data.name and _taken(session, PriceBook, book.tenant_id, "name", data.name, book.id):
        raise DuplicateError("Another price book already has this name.")
    changes = data.changes()
    if changes.get("is_default") is True and not book.is_default:
        _clear_other_defaults(session, book)
    before = {f: getattr(book, f) for f in changes}
    for field, value in changes.items():
        setattr(book, field, value)
    changed = diff(before, {f: getattr(book, f) for f in changes})
    if changed:
        record_audit(
            session,
            principal,
            action="price_book.updated",
            entity_type="price_book",
            entity_id=book.id,
            changes=changed,
        )
    _flush(session, "price book")
    return book


def list_prices(session: Session, principal: Principal, book_id: uuid.UUID) -> list[PriceRead]:
    book = get_price_book(session, principal, book_id)
    rows = session.execute(
        select(PriceBookEntry, Product)
        .join(
            Product,
            (Product.tenant_id == PriceBookEntry.tenant_id)
            & (Product.id == PriceBookEntry.product_id),
        )
        .where(PriceBookEntry.tenant_id == book.tenant_id, PriceBookEntry.price_book_id == book.id)
        .order_by(func.lower(Product.name))
    ).all()
    return [
        PriceRead(
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            unit=product.unit,
            tax_rate=product.tax_rate,
            product_active=product.is_active,
            unit_price=entry.unit_price,
            currency=book.currency,
            updated_at=entry.updated_at,
        )
        for entry, product in rows
    ]


def set_price(
    session: Session,
    principal: Principal,
    book_id: uuid.UUID,
    product_id: uuid.UUID,
    unit_price: Decimal,
) -> None:
    _tenant(principal, manage=True)
    book = get_price_book(session, principal, book_id)
    product = get_product(session, principal, product_id)
    entry = session.scalars(
        select(PriceBookEntry)
        .where(
            PriceBookEntry.tenant_id == book.tenant_id,
            PriceBookEntry.price_book_id == book.id,
            PriceBookEntry.product_id == product.id,
        )
        .with_for_update()
    ).one_or_none()
    old = entry.unit_price if entry else None
    if entry is None:
        session.add(
            PriceBookEntry(
                tenant_id=book.tenant_id,
                price_book_id=book.id,
                product_id=product.id,
                unit_price=unit_price,
            )
        )
    else:
        entry.unit_price = unit_price
    if old != unit_price:
        record_audit(
            session,
            principal,
            action="price.changed",
            entity_type="price_book",
            entity_id=book.id,
            changes={
                "product_id": product.id,
                "sku": product.sku,
                "unit_price": {"old": old, "new": unit_price},
            },
        )
    _flush(session, "price")


def remove_price(
    session: Session, principal: Principal, book_id: uuid.UUID, product_id: uuid.UUID
) -> None:
    _tenant(principal, manage=True)
    book = get_price_book(session, principal, book_id)
    entry = session.scalars(
        select(PriceBookEntry).where(
            PriceBookEntry.tenant_id == book.tenant_id,
            PriceBookEntry.price_book_id == book.id,
            PriceBookEntry.product_id == product_id,
        )
    ).one_or_none()
    if entry is None:
        raise ProductNotFoundError()
    record_audit(
        session,
        principal,
        action="price.removed",
        entity_type="price_book",
        entity_id=book.id,
        changes={"product_id": product_id, "unit_price": {"old": entry.unit_price, "new": None}},
    )
    session.delete(entry)
    _flush(session, "price")
