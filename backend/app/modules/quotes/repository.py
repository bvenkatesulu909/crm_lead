"""Database queries for quotes. Every query goes through the quote policies."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.quotes.models import Quote, QuoteEvent, QuoteLine
from app.modules.quotes.policies import readable_quotes, writable_quotes


@dataclass(frozen=True)
class QuoteFilters:
    q: str | None = None
    statuses: tuple[str, ...] = ()
    account_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    include_superseded: bool = False
    limit: int = 50
    offset: int = 0


def next_quote_number(session: Session, tenant_id: uuid.UUID) -> int:
    """Atomically take the next quote number for this tenant (safe under concurrency)."""
    number = session.scalar(
        text(
            "INSERT INTO quote_number_counters (tenant_id, last_number) VALUES (:t, 1) "
            "ON CONFLICT (tenant_id) DO UPDATE "
            "SET last_number = quote_number_counters.last_number + 1 "
            "RETURNING last_number"
        ),
        {"t": tenant_id},
    )
    if number is None:
        raise RuntimeError("could not allocate a quote number")
    return int(number)


def _filtered(principal: Principal, f: QuoteFilters) -> Select[Quote]:
    statement = select(Quote).where(readable_quotes(principal))
    if f.q:
        term = f.q.strip()
        digits = term.upper().removeprefix("QT-").split("/")[0].lstrip("0")
        conditions: list[ColumnElement[bool]] = [
            Quote.title.ilike(f"%{escape_like(term)}%", escape="\\")
        ]
        if digits.isdigit():
            conditions.append(Quote.number == int(digits))
        statement = statement.where(or_(*conditions))
    if f.statuses:
        statement = statement.where(Quote.status.in_(f.statuses))
    elif not f.include_superseded:
        statement = statement.where(Quote.status != "superseded")
    for column in ("account_id", "opportunity_id", "order_id", "owner_id"):
        value = getattr(f, column)
        if value:
            statement = statement.where(getattr(Quote, column) == value)
    return statement


def search(session: Session, principal: Principal, f: QuoteFilters) -> tuple[Sequence[Quote], int]:
    statement = _filtered(principal, f)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    page = statement.order_by(Quote.created_at.desc(), Quote.id).limit(f.limit).offset(f.offset)
    return session.scalars(page).all(), total


def get_readable(session: Session, principal: Principal, quote_id: uuid.UUID) -> Quote | None:
    return session.scalars(
        select(Quote).where(Quote.id == quote_id, readable_quotes(principal))
    ).one_or_none()


def get_writable(session: Session, principal: Principal, quote_id: uuid.UUID) -> Quote | None:
    return session.scalars(
        select(Quote)
        .where(Quote.id == quote_id, writable_quotes(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def get_in_tenant(session: Session, tenant_id: uuid.UUID, quote_id: uuid.UUID) -> Quote | None:
    """System access (background jobs, which run without a user): tenant-scoped, no policy."""
    return session.scalars(
        select(Quote).where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
    ).one_or_none()


def get_for_customer_decision(
    session: Session, principal: Principal, quote_id: uuid.UUID
) -> Quote | None:
    return session.scalars(
        select(Quote)
        .where(Quote.id == quote_id, readable_quotes(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def lines_of(session: Session, quote: Quote) -> Sequence[QuoteLine]:
    return session.scalars(
        select(QuoteLine)
        .where(QuoteLine.tenant_id == quote.tenant_id, QuoteLine.quote_id == quote.id)
        .order_by(QuoteLine.position)
    ).all()


def delete_lines(session: Session, quote: Quote) -> None:
    session.execute(
        delete(QuoteLine).where(
            QuoteLine.tenant_id == quote.tenant_id, QuoteLine.quote_id == quote.id
        )
    )


def events_of(session: Session, quote: Quote) -> Sequence[QuoteEvent]:
    return session.scalars(
        select(QuoteEvent)
        .where(QuoteEvent.tenant_id == quote.tenant_id, QuoteEvent.quote_id == quote.id)
        .order_by(QuoteEvent.created_at.desc(), QuoteEvent.seq.desc())
    ).all()
