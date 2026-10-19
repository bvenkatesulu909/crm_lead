"""Identity endpoints: who am I, colleague directory, and tenant listing for super admins."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal, UserType
from app.core.auth.rbac import SALES_ROLES, SUPPORT_ROLES, Permission
from app.core.db import get_db_session
from app.modules.identity.dependencies import get_principal, require_any_permission
from app.modules.identity.models import Tenant, User

router = APIRouter(tags=["identity"])

can_read_tenants = require_any_permission(Permission.PLATFORM_TENANT_READ)


class MeResponse(BaseModel):
    user_id: uuid.UUID | None
    display_name: str | None
    email: str | None
    tenant_id: uuid.UUID | None
    tenant_name: str | None
    user_type: UserType
    roles: list[str]
    permissions: list[str]


@router.get("/me", summary="The signed-in user as the API sees them")
def get_me(principal: Principal = Depends(get_principal)) -> MeResponse:
    return MeResponse(
        user_id=principal.user_id,
        display_name=principal.display_name,
        email=principal.email,
        tenant_id=principal.tenant_id,
        tenant_name=principal.tenant_name,
        user_type=principal.user_type,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
    )


class TenantSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    status: str


@router.get("/platform/tenants", summary="List tenants (super admin only)")
def list_tenants(
    _: Principal = Depends(can_read_tenants),
    session: Session = Depends(get_db_session),
) -> list[TenantSummary]:
    tenants = session.scalars(select(Tenant).order_by(Tenant.slug)).all()
    return [TenantSummary(id=t.id, slug=t.slug, name=t.name, status=t.status) for t in tenants]


class DirectoryUser(BaseModel):
    id: uuid.UUID
    display_name: str
    assignable: bool  # active sales employee: can own leads
    support: bool  # can be assigned support tickets


@router.get(
    "/users",
    summary="Colleagues in your organisation (names only)",
    description="Active staff of YOUR tenant, for showing owner names and choosing assignees. "
    "Only names and IDs are returned. `assignable=true` keeps only sales employees who can own "
    "leads. Customers and platform users get 403.",
    responses={403: {"description": "Not a staff member of a tenant"}},
)
def list_users(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    assignable: bool = Query(default=False),
    support: bool = Query(default=False, description="Only people who handle support tickets"),
) -> list[DirectoryUser]:
    if principal.user_type != "staff" or principal.tenant_id is None:
        raise HTTPException(status_code=403, detail="Only staff can see the colleague directory.")
    sales = sorted(role.value for role in SALES_ROLES)
    statement = select(User).where(
        User.tenant_id == principal.tenant_id,
        User.user_type == "staff",
        User.is_active.is_(True),
    )
    support_roles = sorted(role.value for role in SUPPORT_ROLES)
    if assignable:
        statement = statement.where(User.roles.overlap(sales))
    if support:
        statement = statement.where(User.roles.overlap(support_roles))
    users = session.scalars(statement.order_by(User.display_name, User.id).limit(500)).all()
    return [
        DirectoryUser(
            id=u.id,
            display_name=u.display_name,
            assignable=bool(set(u.roles or []) & set(sales)),
            support=bool(set(u.roles or []) & set(support_roles)),
        )
        for u in users
    ]
