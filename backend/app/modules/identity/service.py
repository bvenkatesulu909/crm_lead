"""Turns a verified access token into a Principal, using the CRM database.

Rules:
- The CRM user is looked up by the token's (issuer, subject) only. Tenant and user ID come
  from that row - never from the request.
- Unknown identity: allowed only for super admins (platform users with no tenant).
- Inactive user or suspended tenant: refused.
- Staff users get only staff roles; customer users only the customer role; super admin is
  never combined with tenant membership. Extra roles in the token are ignored.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal, UserType
from app.core.auth.rbac import (
    CUSTOMER_ROLES,
    PLATFORM_ROLES,
    STAFF_ROLES,
    parse_roles,
    permissions_for,
)
from app.core.auth.tokens import VerifiedToken
from app.core.db import bind_tenant
from app.core.errors import ForbiddenError
from app.modules.identity.models import Tenant, User

LAST_SEEN_PRECISION = timedelta(minutes=15)


class AccessPendingError(ForbiddenError):
    code = "access_pending"


class AccountDisabledError(ForbiddenError):
    code = "account_disabled"


def forbidden(detail: str = "You do not have permission to perform this action.") -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def resolve_principal(session: Session, token: VerifiedToken) -> Principal:
    token_roles = parse_roles(token.roles)
    user = session.scalars(
        select(User).where(User.idp_issuer == token.issuer, User.idp_subject == token.subject)
    ).one_or_none()

    if user is None:
        platform_roles = token_roles & PLATFORM_ROLES
        if not platform_roles:
            # Signed up (or invited elsewhere) but no CRM user yet: no data access at all.
            raise AccessPendingError(
                "Your account is waiting for approval by your organisation's administrator."
            )
        return Principal(
            subject=token.subject,
            issuer=token.issuer,
            user_type="platform",
            roles=platform_roles,
            permissions=permissions_for(platform_roles),
        )

    if not user.is_active:
        raise AccountDisabledError(
            "Your CRM account has been deactivated. Please contact your administrator."
        )
    tenant = session.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != "active":
        raise forbidden("Your organisation's CRM access is suspended.")

    # From here on every query runs under RLS with this tenant (ADR 0009). The value comes from
    # the CRM user row, which was found through the verified token - never from the client.
    bind_tenant(session, user.tenant_id)
    user_type: UserType
    if user.user_type == "customer":
        roles, user_type = token_roles & CUSTOMER_ROLES, "customer"
    else:
        roles, user_type = token_roles & STAFF_ROLES, "staff"

    snapshot = sorted(role.value for role in roles)
    changed = False
    if list(user.roles or []) != snapshot:
        # Roles changed in Keycloak since the last request: keep the CRM's copy current.
        user.roles = snapshot
        changed = True
    now = datetime.now(UTC)
    if user.last_login_at is None or now - user.last_login_at > LAST_SEEN_PRECISION:
        # "Last sign-in" for admins. Written at most every 15 minutes, not on every request.
        user.last_login_at = now
        changed = True
    if changed:
        session.commit()

    return Principal(
        subject=token.subject,
        issuer=token.issuer,
        user_type=user_type,
        roles=roles,
        permissions=permissions_for(roles),
        user_id=user.id,
        tenant_id=user.tenant_id,
        display_name=user.display_name,
        email=user.email,
        tenant_name=tenant.name,
    )
