"""Staff endpoints for customer accounts, mounted at /api/v1/accounts.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
Record-level rules (which accounts) live in policies.py; business rules in service.py.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import DomainError, problem_responses
from app.modules.accounts import service
from app.modules.accounts.repository import AccountFilters
from app.modules.accounts.schemas import (
    AccountArchive,
    AccountCreate,
    AccountPage,
    AccountRead,
    AccountRestore,
    AccountStatus,
    AccountStatusChange,
    AccountType,
    AccountUpdate,
    DuplicateCheck,
    Lifecycle,
    Segment,
    TimelineEntry,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/accounts", tags=["accounts"], responses=problem_responses(401, 403))

can_read_accounts = require_any_permission(Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_READ_OWN)
can_write_accounts = require_any_permission(
    Permission.ACCOUNT_WRITE_ALL, Permission.ACCOUNT_WRITE_OWN
)
can_manage_accounts = require_any_permission(Permission.ACCOUNT_WRITE_ALL)

Reader = Annotated[Principal, Depends(can_read_accounts)]
Writer = Annotated[Principal, Depends(can_write_accounts)]
Manager = Annotated[Principal, Depends(can_manage_accounts)]
Db = Annotated[Session, Depends(get_db_session)]


class InvalidFilterError(DomainError):
    status_code = 422
    code = "invalid_filter"


@router.get(
    "",
    summary="List and search the accounts you may see",
    description="`q` searches name and account number (case-insensitive, substring). `total` "
    "counts only accounts you may see. `archived=true` lists archived accounts instead "
    "(managers and administrators only).",
)
def list_accounts(
    principal: Reader,
    session: Db,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    status: AccountStatus | None = None,
    segment: Segment | None = None,
    owner_id: uuid.UUID | None = None,
    parent_account_id: uuid.UUID | None = None,
    industry: str | None = Query(default=None, min_length=1, max_length=100),
    country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
    lifecycle_stage: Lifecycle | None = None,
    account_type: AccountType | None = None,
    min_value: Decimal | None = Query(
        default=None, ge=0, description="Issued invoices in `value_currency` add up to at least"
    ),
    value_currency: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> AccountPage:
    if (min_value is None) != (value_currency is None):
        raise InvalidFilterError("min_value and value_currency go together.")
    filters = AccountFilters(
        q=q.strip() if q else None,
        status=status,
        segment=segment,
        owner_id=owner_id,
        parent_account_id=parent_account_id,
        industry=industry.strip() if industry else None,
        country=country,
        lifecycle_stage=lifecycle_stage,
        account_type=account_type,
        min_value=min_value,
        value_currency=value_currency,
        archived=archived,
        limit=limit,
        offset=offset,
    )
    accounts, total = service.list_accounts(session, principal, filters)
    return AccountPage(
        items=[AccountRead.model_validate(a) for a in accounts],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/duplicates",
    summary="Possible duplicates before creating or renaming an account",
    description="Matches on company name (ignoring case, punctuation and legal forms such as "
    "Ltd/GmbH), website domain and phone number. Matches you may not see are only counted.",
)
def check_duplicates(
    principal: Reader,
    session: Db,
    name: str | None = Query(default=None, min_length=1, max_length=255),
    website: str | None = Query(default=None, min_length=1, max_length=2048),
    phone: str | None = Query(default=None, min_length=1, max_length=50),
    exclude_id: uuid.UUID | None = None,
) -> DuplicateCheck:
    return service.check_duplicates(
        session, principal, name=name, website=website, phone=phone, exclude_id=exclude_id
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description="Sales staff become the owner automatically. Choosing another owner requires "
    "`account:write:all`.",
    responses=problem_responses(404, 409, 422),
)
def create_account(
    data: AccountCreate, principal: Writer, session: Db, response: Response
) -> AccountRead:
    account = service.create_account(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/accounts/{account.id}"
    return AccountRead.model_validate(account)


@router.get("/{account_id}", summary="Get one account", responses=problem_responses(404))
def get_account(account_id: uuid.UUID, principal: Reader, session: Db) -> AccountRead:
    return AccountRead.model_validate(service.get_account(session, principal, account_id))


@router.patch(
    "/{account_id}",
    summary="Change account details",
    description="Send only the fields to change plus `version`. Changing the owner requires "
    "`account:write:all`.",
    responses=problem_responses(404, 409, 422),
)
def update_account(
    account_id: uuid.UUID, data: AccountUpdate, principal: Writer, session: Db
) -> AccountRead:
    account = service.update_account(session, principal, account_id, data)
    session.commit()
    return AccountRead.model_validate(account)


@router.post(
    "/{account_id}/status",
    summary="Deactivate or reactivate an account",
    responses=problem_responses(404, 409, 422),
)
def change_status(
    account_id: uuid.UUID, data: AccountStatusChange, principal: Writer, session: Db
) -> AccountRead:
    account = service.change_status(
        session,
        principal,
        account_id,
        version=data.version,
        status=data.status,
        reason=data.reason,
    )
    session.commit()
    return AccountRead.model_validate(account)


@router.post(
    "/{account_id}/archive",
    summary="Archive an inactive account (managers and administrators)",
    description="The account disappears from lists and screens but nothing is deleted; it can "
    "be restored. It must be inactive and have no child accounts.",
    responses=problem_responses(404, 409, 422),
)
def archive_account(
    account_id: uuid.UUID, data: AccountArchive, principal: Manager, session: Db
) -> AccountRead:
    account = service.archive_account(
        session, principal, account_id, version=data.version, reason=data.reason
    )
    session.commit()
    return AccountRead.model_validate(account)


@router.post(
    "/{account_id}/restore",
    summary="Restore an archived account (managers and administrators)",
    responses=problem_responses(404, 409, 422),
)
def restore_account(
    account_id: uuid.UUID, data: AccountRestore, principal: Manager, session: Db
) -> AccountRead:
    account = service.restore_account(session, principal, account_id, version=data.version)
    session.commit()
    return AccountRead.model_validate(account)


@router.get(
    "/{account_id}/timeline",
    summary="History of the account (newest first)",
    description="Changes to the account and its contacts, from the audit log (last 100).",
    responses=problem_responses(404),
)
def get_timeline(account_id: uuid.UUID, principal: Reader, session: Db) -> list[TimelineEntry]:
    return service.account_timeline(session, principal, account_id)
