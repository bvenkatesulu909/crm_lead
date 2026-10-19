"""Customer-portal endpoints, mounted at /api/v1/portal.

Only principals with ``portal:account:read`` (the customer role) get in; staff are refused here,
and customers are refused on the staff endpoints. Results are limited to the accounts in the
user's portal_access_grants, by the accounts module's policy.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.modules.accounts.api import PortalAccountRead, get_portal_account, list_portal_accounts
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/portal", tags=["portal"])

is_portal_customer = require_any_permission(Permission.PORTAL_ACCOUNT_READ)


@router.get("/accounts", summary="Accounts I am allowed to see as a customer")
def my_accounts(
    principal: Principal = Depends(is_portal_customer),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PortalAccountRead]:
    return list_portal_accounts(session, principal, limit=limit, offset=offset)


@router.get("/accounts/{account_id}", summary="One of my accounts", responses={404: {}})
def my_account(
    account_id: uuid.UUID,
    principal: Principal = Depends(is_portal_customer),
    session: Session = Depends(get_db_session),
) -> PortalAccountRead:
    account = get_portal_account(session, principal, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return account
