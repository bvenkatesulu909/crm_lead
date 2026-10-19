"""Database queries for accounts. Every query takes the principal and applies the policy."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.core import matching
from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.accounts.models import Account
from app.modules.accounts.policies import archived_accounts, readable_accounts

ENTITY = "account"


@dataclass(frozen=True)
class AccountFilters:
    q: str | None = None
    status: str | None = None
    segment: str | None = None
    owner_id: uuid.UUID | None = None
    parent_account_id: uuid.UUID | None = None
    industry: str | None = None
    country: str | None = None
    lifecycle_stage: str | None = None
    account_type: str | None = None
    # Customer value: issued invoices in this currency add up to at least min_value.
    min_value: Decimal | None = None
    value_currency: str | None = None
    archived: bool = False
    limit: int = 50
    offset: int = 0


def search(
    session: Session,
    principal: Principal,
    *,
    limit: int,
    offset: int,
    q: str | None = None,
    status: str | None = None,
) -> tuple[Sequence[Account], int]:
    """A page of the accounts this principal may see, plus how many match in total."""
    return search_filtered(
        session, principal, AccountFilters(q=q, status=status, limit=limit, offset=offset)
    )


def search_filtered(
    session: Session, principal: Principal, filters: AccountFilters
) -> tuple[Sequence[Account], int]:
    scope = archived_accounts(principal) if filters.archived else readable_accounts(principal)
    statement = select(Account).where(scope)
    if filters.q:
        pattern = f"%{escape_like(filters.q)}%"
        statement = statement.where(
            or_(
                Account.name.ilike(pattern, escape="\\"),
                Account.account_number.ilike(pattern, escape="\\"),
            )
        )
    if filters.status:
        statement = statement.where(Account.status == filters.status)
    if filters.segment:
        statement = statement.where(Account.segment == filters.segment)
    if filters.owner_id:
        statement = statement.where(Account.owner_id == filters.owner_id)
    if filters.parent_account_id:
        statement = statement.where(Account.parent_account_id == filters.parent_account_id)
    if filters.industry:
        statement = statement.where(
            Account.industry.ilike(f"%{escape_like(filters.industry)}%", escape="\\")
        )
    for column in ("country", "lifecycle_stage", "account_type"):
        value = getattr(filters, column)
        if value:
            statement = statement.where(getattr(Account, column) == value)
    if filters.min_value is not None and filters.value_currency and principal.tenant_id:
        # Imported here, not at the top: invoices' api imports accounts' api (no cycle).
        from app.modules.invoices import api as invoices_api

        statement = statement.where(
            Account.id.in_(
                invoices_api.accounts_with_value(
                    principal.tenant_id, filters.value_currency, filters.min_value
                )
            )
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    page = statement.order_by(Account.name, Account.id).limit(filters.limit).offset(filters.offset)
    return session.scalars(page).all(), total


def list_readable(
    session: Session, principal: Principal, *, limit: int, offset: int
) -> Sequence[Account]:
    return search(session, principal, limit=limit, offset=offset)[0]


def get_readable(
    session: Session, principal: Principal, account_id: uuid.UUID, *, for_update: bool = False
) -> Account | None:
    """The account, or None if it does not exist OR the principal may not see it.

    ``for_update`` locks the row until the transaction ends, so two simultaneous changes to the
    same account run one after the other.
    """
    statement = select(Account).where(Account.id == account_id, readable_accounts(principal))
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalars(statement).one_or_none()


def get_archived(session: Session, principal: Principal, account_id: uuid.UUID) -> Account | None:
    statement = (
        select(Account)
        .where(Account.id == account_id, archived_accounts(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalars(statement).one_or_none()


def ancestor_ids(session: Session, account: Account, limit: int = 50) -> list[uuid.UUID]:
    """IDs of the parent, grandparent, ... of an account (stops after ``limit`` levels)."""
    found: list[uuid.UUID] = []
    current = account.parent_account_id
    while current is not None and len(found) < limit:
        found.append(current)
        current = session.scalar(
            select(Account.parent_account_id).where(
                Account.tenant_id == account.tenant_id, Account.id == current
            )
        )
    return found


def has_live_children(session: Session, account: Account) -> bool:
    found = session.scalar(
        select(Account.id)
        .where(
            Account.tenant_id == account.tenant_id,
            Account.parent_account_id == account.id,
            Account.deleted_at.is_(None),
        )
        .limit(1)
    )
    return found is not None


def number_taken(
    session: Session, tenant_id: uuid.UUID, number: str, except_id: uuid.UUID | None
) -> bool:
    """Account numbers are unique per tenant, archived accounts included (DB constraint)."""
    statement = select(Account.id).where(
        Account.tenant_id == tenant_id, Account.account_number == number
    )
    if except_id is not None:
        statement = statement.where(Account.id != except_id)
    return session.scalar(statement.limit(1)) is not None


def timeline(session: Session, account: Account, limit: int = 100) -> Sequence[AuditLog]:
    return session.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == account.tenant_id,
            AuditLog.entity_type == ENTITY,
            AuditLog.entity_id == account.id,
        )
        .order_by(AuditLog.occurred_at.desc(), AuditLog.seq.desc())
        .limit(limit)
    ).all()


def duplicate_candidates(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    name: str | None,
    website: str | None,
    phone: str | None,
    exclude_id: uuid.UUID | None,
    limit: int = 20,
) -> list[tuple[Account, list[str]]]:
    """Accounts of the tenant (not archived) that may be the same customer, with the reasons.
    Visibility is decided by the caller - this looks at the whole tenant on purpose."""
    checks: list[tuple[ColumnElement[bool], str]] = []
    if name and (key := matching.company_key(name)):
        checks.append((matching.company_key_sql(Account.name) == key, "Same company name"))
    if website and (key := matching.domain_key(website)):
        checks.append((matching.domain_key_sql(Account.website) == key, "Same website"))
    if phone and (key := matching.phone_key(phone)):
        checks.append((matching.phone_key_sql(Account.phone) == key, "Same phone number"))
    if not checks:
        return []
    statement = select(Account, *(c for c, _ in checks)).where(
        Account.tenant_id == tenant_id,
        Account.deleted_at.is_(None),
        or_(*(c for c, _ in checks)),
    )
    if exclude_id is not None:
        statement = statement.where(Account.id != exclude_id)
    rows = session.execute(statement.order_by(Account.name).limit(limit)).all()
    return [
        (row[0], [reason for (_, reason), hit in zip(checks, row[1:], strict=True) if hit])
        for row in rows
    ]
