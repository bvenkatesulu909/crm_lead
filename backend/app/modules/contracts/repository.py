"""Database queries for contracts. Every user-facing query goes through the contract policies."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import ColumnElement, Select, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.contracts.models import Contract, ContractEvent
from app.modules.contracts.policies import readable_contracts, writable_contracts


@dataclass(frozen=True)
class ContractFilters:
    q: str | None = None
    statuses: tuple[str, ...] = ()
    account_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    # Active contracts whose end date is within this many days (for "renewals coming up").
    ending_within_days: int | None = None
    today: date | None = None
    limit: int = 50
    offset: int = 0


def next_contract_number(session: Session, tenant_id: uuid.UUID) -> int:
    """Atomically take the next contract number for this tenant (safe under concurrency)."""
    number = session.scalar(
        text(
            "INSERT INTO contract_number_counters (tenant_id, last_number) VALUES (:t, 1) "
            "ON CONFLICT (tenant_id) DO UPDATE "
            "SET last_number = contract_number_counters.last_number + 1 "
            "RETURNING last_number"
        ),
        {"t": tenant_id},
    )
    if number is None:
        raise RuntimeError("could not allocate a contract number")
    return int(number)


def _filtered(principal: Principal, f: ContractFilters) -> Select[Contract]:
    statement = select(Contract).where(readable_contracts(principal))
    if f.q:
        term = f.q.strip()
        digits = term.upper().removeprefix("CT-").lstrip("0")
        conditions: list[ColumnElement[bool]] = [
            Contract.title.ilike(f"%{escape_like(term)}%", escape="\\")
        ]
        if digits.isdigit():
            conditions.append(Contract.number == int(digits))
        statement = statement.where(or_(*conditions))
    if f.statuses:
        statement = statement.where(Contract.status.in_(f.statuses))
    if f.account_id:
        statement = statement.where(Contract.account_id == f.account_id)
    if f.owner_id:
        statement = statement.where(Contract.owner_id == f.owner_id)
    if f.ending_within_days is not None and f.today is not None:
        statement = statement.where(
            Contract.status == "active",
            Contract.end_date >= f.today,
            Contract.end_date <= f.today + timedelta(days=f.ending_within_days),
        )
    return statement


def search(
    session: Session, principal: Principal, f: ContractFilters
) -> tuple[Sequence[Contract], int]:
    statement = _filtered(principal, f)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    # Contracts that end soonest first when looking at renewals; otherwise newest first.
    order = (
        (Contract.end_date.asc(), Contract.id)
        if f.ending_within_days is not None
        else (Contract.created_at.desc(), Contract.id)
    )
    page = statement.order_by(*order).limit(f.limit).offset(f.offset)
    return session.scalars(page).all(), total


def get_readable(session: Session, principal: Principal, contract_id: uuid.UUID) -> Contract | None:
    return session.scalars(
        select(Contract).where(Contract.id == contract_id, readable_contracts(principal))
    ).one_or_none()


def get_writable(session: Session, principal: Principal, contract_id: uuid.UUID) -> Contract | None:
    return session.scalars(
        select(Contract)
        .where(Contract.id == contract_id, writable_contracts(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def get_in_tenant(
    session: Session, tenant_id: uuid.UUID, contract_id: uuid.UUID
) -> Contract | None:
    """System access (background jobs, which run without a user): tenant-scoped, no policy."""
    return session.scalars(
        select(Contract)
        .where(Contract.tenant_id == tenant_id, Contract.id == contract_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def due_for_expiry(
    session: Session, tenant_id: uuid.UUID, today: date, limit: int
) -> Sequence[Contract]:
    """Active contracts whose end date has passed. Rows are locked and skipped if another
    worker already holds them, so two workers never expire the same contract twice."""
    return session.scalars(
        select(Contract)
        .where(
            Contract.tenant_id == tenant_id,
            Contract.status == "active",
            Contract.end_date < today,
        )
        .order_by(Contract.end_date, Contract.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all()


def due_for_reminder(
    session: Session, tenant_id: uuid.UUID, today: date, limit: int
) -> Sequence[Contract]:
    """Active contracts whose renewal date has come (end date minus notice days), that have
    not ended yet and have not been reminded for this renewal date."""
    return session.scalars(
        select(Contract)
        .where(
            Contract.tenant_id == tenant_id,
            Contract.status == "active",
            Contract.end_date >= today,
            Contract.end_date - Contract.renewal_notice_days <= today,
            Contract.renewal_reminded_at.is_(None),
        )
        .order_by(Contract.end_date, Contract.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all()


def renewal_of(session: Session, contract: Contract) -> Contract | None:
    """The contract that renews this one (a draft or later), if somebody already made it."""
    return session.scalars(
        select(Contract).where(
            Contract.tenant_id == contract.tenant_id, Contract.renewed_from_id == contract.id
        )
    ).first()


def events_of(session: Session, contract: Contract) -> Sequence[ContractEvent]:
    return session.scalars(
        select(ContractEvent)
        .where(
            ContractEvent.tenant_id == contract.tenant_id,
            ContractEvent.contract_id == contract.id,
        )
        .order_by(ContractEvent.created_at.desc(), ContractEvent.seq.desc())
    ).all()
