"""Public interface of the contracts module: what other modules and the worker may import."""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.contracts import repository, service
from app.modules.contracts.models import Contract
from app.modules.contracts.policies import readable_contracts
from app.modules.contracts.rules import label

__all__ = ["label", "contract_brief", "contract_people", "next_renewal", "run_schedules"]


def contract_brief(
    session: Session, principal: Principal, contract_id: uuid.UUID
) -> tuple[str, uuid.UUID, uuid.UUID | None] | None:
    """("CT-0007: title", owner, creator) for a contract this principal may see, else None."""
    contract = repository.get_readable(session, principal, contract_id)
    if contract is None:
        return None
    return (
        f"{label(contract.number)}: {contract.title}",
        contract.owner_id,
        contract.created_by_user_id,
    )


def next_renewal(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> tuple[uuid.UUID, str, date] | None:
    """(id, "CT-0007", end date) of the active contract of an account that ends first, among
    those this person may read; None when there is none (the deal desk, ADR 0024)."""
    row = session.execute(
        select(Contract.id, Contract.number, Contract.end_date)
        .where(
            Contract.account_id == account_id,
            Contract.status == "active",
            Contract.end_date.is_not(None),
            readable_contracts(principal),
        )
        .order_by(Contract.end_date)
        .limit(1)
    ).first()
    if row is None or row.end_date is None:
        return None
    return row.id, label(row.number), row.end_date


def contract_people(
    session: Session, tenant_id: uuid.UUID, contract_id: uuid.UUID
) -> set[uuid.UUID]:
    """Owner and creator of a contract, for notifications. The caller still checks for each
    person whether they may see the contract (contract_brief)."""
    contract = repository.get_in_tenant(session, tenant_id, contract_id)
    if contract is None:
        return set()
    return {p for p in (contract.owner_id, contract.created_by_user_id) if p is not None}


def run_schedules(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    """Expiry sweep and renewal reminders for one organisation (called by the worker)."""
    return service.run_schedules(session, now, tenant_id=tenant_id)
