"""Customer (account) figures for dashboards. Applies ``readable_accounts``."""

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import Filters
from app.modules.accounts.models import Account
from app.modules.accounts.policies import readable_accounts


@dataclass(frozen=True)
class CustomerMetrics:
    total: int  # all customer accounts in scope (now)
    active: int
    new_in_period: int


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = readable_accounts(principal)
    if filters.owner_id is not None:
        condition = and_(condition, Account.owner_id == filters.owner_id)
    return condition


def customer_metrics(session: Session, principal: Principal, filters: Filters) -> CustomerMetrics:
    scope = _scope(principal, filters)
    total, active = session.execute(
        select(func.count(), func.count().filter(Account.status == "active")).where(scope)
    ).one()
    period = filters.period
    new = session.scalar(
        select(func.count()).where(
            scope, Account.created_at >= period.start, Account.created_at < period.end
        )
    )
    return CustomerMetrics(total, active, new or 0)


def customers_by_owner(
    session: Session, principal: Principal, filters: Filters
) -> dict[uuid.UUID | None, int]:
    counts: dict[uuid.UUID | None, int] = defaultdict(int)
    for owner, count in session.execute(
        select(Account.owner_id, func.count())
        .where(_scope(principal, filters))
        .group_by(Account.owner_id)
    ).all():
        counts[owner] = count
    return dict(counts)


def accounts_owned_by(tenant_id: uuid.UUID, owner_id: uuid.UUID) -> Select[uuid.UUID]:
    """Subquery: account IDs of one sales rep (for "filter by rep" in other modules)."""
    return select(Account.id).where(
        Account.tenant_id == tenant_id, Account.owner_id == owner_id, Account.deleted_at.is_(None)
    )
