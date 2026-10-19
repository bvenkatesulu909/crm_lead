"""Public interface of the identity module. Other modules import only from here."""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import (
    AUTOMATION_PERMISSIONS,
    SALES_ROLES,
    STAFF_ROLES,
    SUPPORT_ROLES,
    Permission,
    Role,
    parse_roles,
    permissions_for,
)
from app.modules.identity.dependencies import get_principal, require_any_permission
from app.modules.identity.models import PortalAccessGrant, Tenant, User

__all__ = [
    "staff_with_role",
    "AUTOMATION_ISSUER",
    "automation_principal",
    "get_principal",
    "granted_account_ids",
    "is_assignable_sales_user",
    "is_assignable_support_user",
    "is_active_staff_member",
    "people_by_id",
    "require_any_permission",
    "sales_people",
    "staff_email",
    "staff_principal",
    "staff_with_permission",
    "staff_member_exists",
    "tenant_name",
]


def granted_account_ids(principal: Principal) -> Select[uuid.UUID]:
    """Subquery: IDs of the customer accounts this portal user has been granted."""
    return select(PortalAccessGrant.account_id).where(
        PortalAccessGrant.tenant_id == principal.tenant_id,
        PortalAccessGrant.user_id == principal.user_id,
    )


def _is_active_staff_with(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, roles: frozenset[Role]
) -> bool:
    user = session.scalars(
        select(User).where(
            User.tenant_id == tenant_id,
            User.id == user_id,
            User.user_type == "staff",
            User.is_active.is_(True),
        )
    ).one_or_none()
    return user is not None and bool(set(user.roles or []) & {r.value for r in roles})


def is_assignable_sales_user(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True if the user is an active staff member of THIS tenant with a sales role."""
    return _is_active_staff_with(session, tenant_id, user_id, SALES_ROLES)


def is_active_staff_member(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True if the user is an active staff member of THIS tenant (any staff role)."""
    return _is_active_staff_with(session, tenant_id, user_id, STAFF_ROLES)


def is_assignable_support_user(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True if the user is an active staff member of THIS tenant who handles support."""
    return _is_active_staff_with(session, tenant_id, user_id, SUPPORT_ROLES)


def people_by_id(
    session: Session, tenant_id: uuid.UUID, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    """{user id: (display name, user type)} for users of this tenant, e.g. comment authors."""
    if not user_ids:
        return {}
    rows = session.execute(
        select(User.id, User.display_name, User.user_type).where(
            User.tenant_id == tenant_id, User.id.in_(user_ids)
        )
    ).all()
    return {row.id: (row.display_name, row.user_type) for row in rows}


def sales_people(session: Session, tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """(id, name) of the active staff of this tenant with a sales role, by name."""
    users = session.scalars(
        select(User)
        .where(User.tenant_id == tenant_id, User.user_type == "staff", User.is_active.is_(True))
        .order_by(User.display_name)
    ).all()
    sales = {r.value for r in SALES_ROLES}
    return [(u.id, u.display_name) for u in users if set(u.roles or []) & sales]


def staff_member_exists(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True if this staff user belongs to this tenant (active or not)."""
    found = session.scalar(
        select(User.id).where(
            User.tenant_id == tenant_id, User.id == user_id, User.user_type == "staff"
        )
    )
    return found is not None


def tenant_name(session: Session, tenant_id: uuid.UUID) -> str | None:
    """The organisation's display name, for system-generated documents (e.g. a quote PDF).
    No record policy: callers must already have authorized the record that needs it."""
    return session.scalar(select(Tenant.name).where(Tenant.id == tenant_id))


def staff_email(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """E-mail of an active staff member (e.g. Reply-To of a quote e-mail), else None."""
    return session.scalar(
        select(User.email).where(
            User.tenant_id == tenant_id,
            User.id == user_id,
            User.user_type == "staff",
            User.is_active.is_(True),
        )
    )


def staff_principal(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Principal | None:
    """The principal an ACTIVE staff member would have (roles from their last sign-in), or None.

    Used by background work (notifications, ADR 0006) to check what that person may see before
    telling them about a record. Never used to act on anyone's behalf."""
    row = session.execute(
        select(
            User.id, User.idp_subject, User.idp_issuer, User.roles, User.display_name, User.email
        )
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            User.tenant_id == tenant_id,
            User.id == user_id,
            User.user_type == "staff",
            User.is_active.is_(True),
            Tenant.status == "active",
        )
    ).first()
    if row is None:
        return None
    roles = parse_roles(frozenset(row.roles or [])) & STAFF_ROLES
    return Principal(
        subject=row.idp_subject,
        issuer=row.idp_issuer,
        user_type="staff",
        roles=roles,
        permissions=permissions_for(roles),
        user_id=row.id,
        tenant_id=tenant_id,
        display_name=row.display_name,
        email=row.email,
    )


def staff_with_permission(
    session: Session, tenant_id: uuid.UUID, permission: Permission
) -> list[uuid.UUID]:
    """Active staff whose roles (as of their last sign-in) include ``permission``."""
    rows = session.execute(
        select(User.id, User.roles).where(
            User.tenant_id == tenant_id, User.user_type == "staff", User.is_active.is_(True)
        )
    ).all()
    return [
        row.id
        for row in rows
        if permission in permissions_for(parse_roles(frozenset(row.roles or [])) & STAFF_ROLES)
    ]


AUTOMATION_ISSUER = "urn:crm-lead:automation"  # never a real token issuer: no one can sign in


def automation_principal(session: Session, tenant_id: uuid.UUID) -> Principal:
    """The tenant's "Automation" identity for workflow rules (created on first use).

    It acts like a staff member with the fixed AUTOMATION_PERMISSIONS, only inside this tenant,
    so every module's own rules and audit apply to what a rule does."""
    subject = f"automation:{tenant_id}"
    user = session.scalars(
        select(User).where(User.idp_issuer == AUTOMATION_ISSUER, User.idp_subject == subject)
    ).one_or_none()
    if user is None:
        user = User(
            tenant_id=tenant_id,
            idp_issuer=AUTOMATION_ISSUER,
            idp_subject=subject,
            email="automation@crm-lead.invalid",
            display_name="Automation",
            user_type="automation",
        )
        session.add(user)
        session.flush()
    return Principal(
        subject=subject,
        issuer=AUTOMATION_ISSUER,
        user_type="staff",  # passes the staff checks; the permissions are what limit it
        roles=frozenset(),
        permissions=AUTOMATION_PERMISSIONS,
        user_id=user.id,
        tenant_id=tenant_id,
        display_name="Automation",
    )


def staff_with_role(session: Session, tenant_id: uuid.UUID, role: Role) -> list[uuid.UUID]:
    """Active staff whose roles (as of their last sign-in) include ``role``."""
    rows = session.execute(
        select(User.id, User.roles).where(
            User.tenant_id == tenant_id, User.user_type == "staff", User.is_active.is_(True)
        )
    ).all()
    return [row.id for row in rows if role.value in (row.roles or [])]
