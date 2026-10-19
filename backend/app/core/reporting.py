"""Shared building blocks for dashboard figures.

Each business module computes its own figures (in its ``metrics.py``, exported through its
``api.py``) with its OWN record-level policy, so a dashboard can never show more than the user
could open in that module's screens. The dashboard module only combines them.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import InstrumentedAttribute, Session


@dataclass(frozen=True)
class Period:
    """A date range, inclusive of both days, interpreted in UTC."""

    start_date: date
    end_date: date

    @property
    def start(self) -> datetime:
        return datetime.combine(self.start_date, time.min, tzinfo=UTC)

    @property
    def end(self) -> datetime:
        """Exclusive upper bound: midnight after the last day."""
        return datetime.combine(self.end_date + timedelta(days=1), time.min, tzinfo=UTC)


@dataclass(frozen=True)
class Filters:
    period: Period
    # Narrow to records owned by one sales rep. Only for users who may see everyone's records;
    # the dashboard service checks that before passing it on.
    owner_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Money:
    """An amount in one currency. Different currencies are never added together."""

    currency: str
    amount: Decimal


def money_by_currency(rows: Iterable[tuple[str, Decimal | None]]) -> list[Money]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for currency, amount in rows:
        # None = nothing to add (e.g. opportunities without an amount): no "0.00" entry for it.
        if amount is not None:
            totals[currency] += amount
    return [Money(c, totals[c]) for c in sorted(totals)]


@dataclass(frozen=True)
class ActivityItem:
    """One entry of the "recent customer activity" feed."""

    at: datetime
    kind: str  # e.g. "lead.call", "ticket.opened", "order.shipped"
    title: str
    detail: str | None
    record_type: str  # "lead" | "ticket" | "order"
    record_id: uuid.UUID
    actor_user_id: uuid.UUID | None


# --- reports and exports (Phase 18) -------------------------------------------------------

ColumnKind = Literal["text", "number", "money", "percent", "date", "datetime", "user", "account"]
Cell = str | int | Decimal | date | datetime | uuid.UUID | None


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: ColumnKind = "text"


@dataclass(frozen=True)
class Table:
    """A report section: the reports module turns it into JSON or CSV. "user" and "account"
    cells hold IDs; the reports module replaces them with names."""

    title: str
    columns: tuple[Column, ...]
    rows: list[dict[str, Cell]]


@dataclass(frozen=True)
class ExportFilters:
    """Report builder filters. The period is matched against the record's creation time."""

    period: Period | None = None
    owner_id: uuid.UUID | None = None
    status: str | None = None
    limit: int = 200


@dataclass(frozen=True)
class ExportSpec:
    """What a module offers to the report builder for one record type."""

    columns: tuple[Column, ...]
    statuses: tuple[str, ...]


def percent(part: int, whole: int) -> Decimal | None:
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1")) if whole else None


def export_rows(
    session: Session,
    *,
    entity: Any,
    columns: Mapping[str, ColumnElement[Any] | InstrumentedAttribute[Any]],
    wanted: Sequence[str],
    condition: ColumnElement[bool],
    created: InstrumentedAttribute[Any],
    owner: InstrumentedAttribute[Any] | None,
    status: InstrumentedAttribute[Any] | None,
    filters: ExportFilters,
) -> list[dict[str, Cell]]:
    """Rows for the report builder: only ``wanted`` columns (from the module's whitelist), only
    records matching ``condition`` - the module's own record-level policy - newest first."""
    query = (
        select(*(columns[key].label(key) for key in wanted)).select_from(entity).where(condition)
    )
    if filters.period is not None:
        query = query.where(created >= filters.period.start, created < filters.period.end)
    if filters.owner_id is not None and owner is not None:
        query = query.where(owner == filters.owner_id)
    if filters.status is not None and status is not None:
        query = query.where(status == filters.status)
    rows = session.execute(query.order_by(created.desc()).limit(filters.limit)).mappings().all()
    return [dict(row) for row in rows]
