"""Public interface of the accounts module. Other modules import only from here."""

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.accounts import repository, service
from app.modules.accounts.metrics import (
    CustomerMetrics,
    accounts_owned_by,
    customer_metrics,
    customers_by_owner,
)
from app.modules.accounts.models import ACCOUNT_SEGMENTS as models_ACCOUNT_SEGMENTS
from app.modules.accounts.models import ACCOUNT_STATUSES, Account
from app.modules.accounts.policies import readable_accounts
from app.modules.accounts.repository import AccountFilters
from app.modules.accounts.schemas import PortalAccountRead
from app.modules.accounts.service import (
    get_account,
    readable_summaries,
    record_account_event,
    set_segment,
    transfer_owner,
)

__all__ = [
    "account_names",
    "EXPORT",
    "export_table",
    "set_account_segment",
    "account_owner_id",
    "ACCOUNT_SEGMENTS",
    "CustomerMetrics",
    "PortalAccountRead",
    "account_name",
    "accounts_owned_by",
    "customer_metrics",
    "customers_by_owner",
    "create_account",
    "get_account",
    "get_portal_account",
    "is_owned_account",
    "is_readable_account",
    "list_portal_accounts",
    "owned_account_ids",
    "readable_summaries",
    "record_account_event",
    "transfer_owner",
]


def list_portal_accounts(
    session: Session, principal: Principal, *, limit: int, offset: int
) -> list[PortalAccountRead]:
    accounts = repository.list_readable(session, principal, limit=limit, offset=offset)
    return [PortalAccountRead.model_validate(account) for account in accounts]


def get_portal_account(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> PortalAccountRead | None:
    account = repository.get_readable(session, principal, account_id)
    return PortalAccountRead.model_validate(account) if account else None


def is_readable_account(session: Session, principal: Principal, account_id: uuid.UUID) -> bool:
    """True if the account exists, is in the principal's tenant and the principal may see it."""
    return repository.get_readable(session, principal, account_id) is not None


def is_owned_account(session: Session, principal: Principal, account_id: uuid.UUID) -> bool:
    """True if the account exists in the principal's tenant, is not deleted and they own it."""
    found = session.scalar(owned_account_ids(principal).where(Account.id == account_id))
    return found is not None


def create_account(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    website: str | None,
    phone: str | None,
    owner_id: uuid.UUID | None,
) -> uuid.UUID:
    """Insert an account in the caller's transaction (authorization is the caller's job)."""
    account = Account(
        tenant_id=tenant_id, name=name, website=website, phone=phone, owner_id=owner_id
    )
    session.add(account)
    session.flush()
    return account.id


def owned_account_ids(principal: Principal) -> Select[uuid.UUID]:
    """Subquery: IDs of the (not deleted) accounts this user owns in their tenant."""
    return select(Account.id).where(
        Account.tenant_id == principal.tenant_id,
        Account.owner_id == principal.user_id,
        Account.deleted_at.is_(None),
    )


def account_name(session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID) -> str | None:
    """An account's name, for system-generated documents (e.g. a quote PDF).
    No record policy: callers must already have authorized the record that needs it."""
    return session.scalar(
        select(Account.name).where(Account.tenant_id == tenant_id, Account.id == account_id)
    )


ACCOUNT_SEGMENTS = models_ACCOUNT_SEGMENTS


def account_owner_id(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> uuid.UUID | None:
    account = repository.get_readable(session, principal, account_id)
    return account.owner_id if account else None


def set_account_segment(
    session: Session, principal: Principal, account_id: uuid.UUID, segment: str
) -> None:
    """Change an account's segment with the accounts module's own checks and audit."""
    set_segment(session, principal, account_id, segment)


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("name", "Name", "text"),
        Column("account_number", "Account no.", "text"),
        Column("industry", "Industry", "text"),
        Column("segment", "Segment", "text"),
        Column("lifecycle_stage", "Lifecycle stage", "text"),
        Column("country", "Country", "text"),
        Column("city", "City", "text"),
        Column("phone", "Phone", "text"),
        Column("website", "Website", "text"),
        Column("status", "Status", "text"),
        Column("owner_id", "Owner", "user"),
    ),
    statuses=ACCOUNT_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Account,
        columns={key: getattr(Account, key) for key in allowed},
        wanted=wanted,
        condition=readable_accounts(principal),
        created=Account.created_at,
        owner=Account.owner_id,
        status=Account.status,
        filters=filters,
    )


def account_names(
    session: Session, tenant_id: uuid.UUID, account_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """{id: name} for labelling report rows that were already filtered by their own module's
    policy (a reader of an order may see its customer's name). Tenant-scoped."""
    if not account_ids:
        return {}
    rows = session.execute(
        select(Account.id, Account.name).where(
            Account.tenant_id == tenant_id, Account.id.in_(account_ids)
        )
    ).all()
    return {row.id: row.name for row in rows}


# --- staff assistant (read-only, record-policy enforced) -------------------------------------


def search_accounts(
    session: Session, principal: Principal, *, q: str = "", limit: int = 20
) -> list[dict[str, Any]]:
    if not (
        principal.has_permission(Permission.ACCOUNT_READ_ALL)
        or principal.has_permission(Permission.ACCOUNT_READ_OWN)
    ):
        raise ForbiddenError("You may not read accounts.")
    items, _ = service.list_accounts(
        session, principal, AccountFilters(q=q.strip()[:100] or None, limit=min(limit, 50))
    )
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "status": item.status,
            "segment": item.segment,
            "industry": item.industry,
            "country": item.country,
        }
        for item in items
    ]


def get_account_brief(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> dict[str, Any]:
    account = service.get_account(session, principal, account_id)
    return {
        "id": str(account.id),
        "name": account.name,
        "status": account.status,
        "segment": account.segment,
        "industry": account.industry,
        "country": account.country,
        "link": f"/accounts/{account.id}",
    }
