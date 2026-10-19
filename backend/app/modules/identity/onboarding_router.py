"""User administration and onboarding endpoints (ADR 0004). Thin: permission gate, call the
service, commit once.

- /tenant/...                      Tenant Admin: users, roles, sign-up code, access requests
- /accounts/{id}/portal-users      staff: who can see this account in the portal; invitations
- /onboarding/...                  a signed-in person WITHOUT CRM access: status and request
- /platform/tenants (POST)         Super Admin: new organisation with its first admin
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth.identity_admin import IdentityAdmin
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.auth.tokens import VerifiedToken
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity import onboarding as service
from app.modules.identity.dependencies import get_verified_token, require_any_permission
from app.modules.identity.onboarding_schemas import (
    AccessRequestApproval,
    AccessRequestRead,
    AdminUserRead,
    OnboardingStatus,
    PortalInvite,
    PortalUserRead,
    RoleChange,
    SignupCodeRead,
    SignupRequest,
    StaffUserCreate,
    TenantCreate,
    TenantCreated,
)

Db = Annotated[Session, Depends(get_db_session)]
UserReader = Annotated[Principal, Depends(require_any_permission(Permission.TENANT_USER_READ))]
UserManager = Annotated[Principal, Depends(require_any_permission(Permission.TENANT_USER_MANAGE))]
AccountReader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_READ_OWN)),
]
Inviter = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_USER_INVITE))]
PlatformAdmin = Annotated[
    Principal, Depends(require_any_permission(Permission.PLATFORM_TENANT_MANAGE))
]
Token = Annotated[VerifiedToken, Depends(get_verified_token)]


def identity_admin(request: Request) -> IdentityAdmin:
    admin: IdentityAdmin = request.app.state.identity_admin
    return admin


def issuer(request: Request) -> str:
    return str(request.app.state.settings.oidc_issuer)


Admin = Annotated[IdentityAdmin, Depends(identity_admin)]
Issuer = Annotated[str, Depends(issuer)]

# --- tenant administration ----------------------------------------------------------------

tenant_router = APIRouter(
    prefix="/tenant", tags=["user administration"], responses=problem_responses(401, 403)
)


@tenant_router.get("/users", summary="Everyone in your organisation (staff and portal users)")
def list_users(principal: UserReader, session: Db) -> list[AdminUserRead]:
    return service.list_users(session, principal)


@tenant_router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    summary="Add a staff member (they get a set-your-password e-mail)",
    responses=problem_responses(409, 422, 503),
)
def create_user(
    data: StaffUserCreate, principal: UserManager, session: Db, admin: Admin, iss: Issuer
) -> AdminUserRead:
    user = service.create_staff_user(
        session,
        principal,
        admin,
        issuer=iss,
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        role=data.role,
    )
    session.commit()
    return user


@tenant_router.put(
    "/users/{user_id}/role",
    summary="Change a staff member's role (effective at their next token refresh)",
    responses=problem_responses(404, 409, 422, 503),
)
def change_role(
    user_id: uuid.UUID, data: RoleChange, principal: UserManager, session: Db, admin: Admin
) -> AdminUserRead:
    user = service.change_role(session, principal, admin, user_id, data.role)
    session.commit()
    return user


@tenant_router.post(
    "/users/{user_id}/deactivate",
    summary="Block sign-in and end their sessions",
    responses=problem_responses(404, 409, 503),
)
def deactivate(
    user_id: uuid.UUID, principal: UserManager, session: Db, admin: Admin
) -> AdminUserRead:
    user = service.set_active(session, principal, admin, user_id, False)
    session.commit()
    return user


@tenant_router.post(
    "/users/{user_id}/reactivate",
    summary="Allow sign-in again",
    responses=problem_responses(404, 503),
)
def reactivate(
    user_id: uuid.UUID, principal: UserManager, session: Db, admin: Admin
) -> AdminUserRead:
    user = service.set_active(session, principal, admin, user_id, True)
    session.commit()
    return user


@tenant_router.post(
    "/users/{user_id}/resend-invite",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Send the set-your-password e-mail again",
    responses=problem_responses(404, 409, 503),
)
def resend_invite(
    user_id: uuid.UUID, principal: UserManager, session: Db, admin: Admin
) -> Response:
    service.resend_invite(session, principal, admin, user_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@tenant_router.get("/signup-code", summary="The code people enter when they sign up themselves")
def get_signup_code(principal: UserManager, session: Db) -> SignupCodeRead:
    return SignupCodeRead(signup_code=service.signup_code(session, principal))


@tenant_router.post(
    "/signup-code/regenerate", summary="Replace the sign-up code (the old one stops working)"
)
def regenerate_signup_code(principal: UserManager, session: Db) -> SignupCodeRead:
    code = service.regenerate_signup_code(session, principal)
    session.commit()
    return SignupCodeRead(signup_code=code)


@tenant_router.get("/access-requests", summary="People waiting for approval")
def list_access_requests(principal: UserManager, session: Db) -> list[AccessRequestRead]:
    return service.list_access_requests(session, principal)


@tenant_router.post(
    "/access-requests/{request_id}/approve",
    summary="Approve: choose a staff role, or 'customer' with the accounts they may see",
    responses=problem_responses(404, 409, 422, 503),
)
def approve(
    request_id: uuid.UUID,
    data: AccessRequestApproval,
    principal: UserManager,
    session: Db,
    admin: Admin,
) -> AdminUserRead:
    user = service.approve_access_request(
        session, principal, admin, request_id, role=data.role, account_ids=data.account_ids
    )
    session.commit()
    return user


@tenant_router.post(
    "/access-requests/{request_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject (the person keeps no access)",
    responses=problem_responses(404),
)
def reject(request_id: uuid.UUID, principal: UserManager, session: Db) -> Response:
    service.reject_access_request(session, principal, request_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- portal access per account ------------------------------------------------------------

portal_access_router = APIRouter(
    prefix="/accounts/{account_id}/portal-users",
    tags=["portal access"],
    responses=problem_responses(401, 403, 404),
)


@portal_access_router.get("", summary="Customers who can see this account in the portal")
def list_portal_users(
    account_id: uuid.UUID, principal: AccountReader, session: Db
) -> list[PortalUserRead]:
    return service.portal_users(session, principal, account_id)


@portal_access_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a customer contact to the portal for this account",
    description="Tenant admins: any account. Sales agents: accounts they own. An existing "
    "portal user with this e-mail simply gets access to this account too.",
    responses=problem_responses(409, 422, 503),
)
def invite(
    account_id: uuid.UUID,
    data: PortalInvite,
    principal: Inviter,
    session: Db,
    admin: Admin,
    iss: Issuer,
) -> PortalUserRead:
    user = service.invite_portal_user(
        session,
        principal,
        admin,
        account_id,
        issuer=iss,
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
    )
    session.commit()
    return user


@portal_access_router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove this customer's access to this account",
)
def revoke(account_id: uuid.UUID, user_id: uuid.UUID, principal: Inviter, session: Db) -> Response:
    service.revoke_portal_access(session, principal, account_id, user_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- onboarding (signed in, no CRM access yet) --------------------------------------------

onboarding_router = APIRouter(
    prefix="/onboarding", tags=["onboarding"], responses=problem_responses(401)
)


@onboarding_router.get("/status", summary="Do I have access, or is my request waiting?")
def onboarding_status(token: Token, session: Db) -> OnboardingStatus:
    return service.onboarding_status(session, token)


@onboarding_router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    summary="Ask to join the organisation with this sign-up code",
    description="Needs a verified e-mail. Wrong codes are limited to 5 per hour.",
    responses=problem_responses(403, 409, 422, 429),
)
def submit_request(data: SignupRequest, token: Token, session: Db) -> OnboardingStatus:
    try:
        result = service.submit_access_request(session, token, data.signup_code)
    finally:
        # Wrong-code attempts must be kept even though the request itself fails.
        session.commit()
    return result


# --- platform -----------------------------------------------------------------------------

platform_router = APIRouter(
    prefix="/platform", tags=["platform"], responses=problem_responses(401, 403)
)


@platform_router.post(
    "/tenants",
    status_code=status.HTTP_201_CREATED,
    summary="Create an organisation and its first Tenant Admin (super admin)",
    responses=problem_responses(409, 422, 503),
)
def create_tenant(
    data: TenantCreate, principal: PlatformAdmin, session: Db, admin: Admin, iss: Issuer
) -> TenantCreated:
    tenant, user = service.create_tenant(
        session,
        principal,
        admin,
        issuer=iss,
        slug=data.slug,
        name=data.name,
        admin_email=data.admin_email,
        admin_first_name=data.admin_first_name,
        admin_last_name=data.admin_last_name,
    )
    session.commit()
    return TenantCreated(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        signup_code=tenant.signup_code,
        admin_user_id=user.id,
    )
