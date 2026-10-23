"""User administration and onboarding (ADR 0004). Functions never commit; routers commit once.

Three ways in, all ending in a CRM ``users`` row that only an administrator can create:
1. A Tenant Admin adds a staff member  -> Keycloak login + CRM user + set-your-password e-mail.
2. Staff invite a customer contact to the portal for one account -> customer user + grant.
3. Someone signs up in Keycloak, enters their organisation's sign-up code and waits; a Tenant
   Admin approves (choosing role / accounts) or rejects the request.

Keycloak and PostgreSQL cannot share a transaction. A login created in Keycloak is deleted again
if anything after it fails ("compensating action"), so no orphan logins remain.
"""

import logging
import secrets
import uuid
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.identity_admin import IdentityAdmin, IdentityConflictError, NewIdentity
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role
from app.core.auth.tokens import VerifiedToken
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.identity.models import (
    SIGNUP_CODE_ALPHABET,
    AccessRequest,
    PortalAccessGrant,
    SignupCodeAttempt,
    Tenant,
    User,
)
from app.modules.identity.onboarding_schemas import (
    AccessRequestRead,
    AdminUserRead,
    OnboardingStatus,
    PortalUserRead,
)

logger = logging.getLogger(__name__)

MAX_CODE_ATTEMPTS_PER_HOUR = 5


class UserNotFoundError(NotFoundError):
    code = "user_not_found"

    def __init__(self) -> None:
        super().__init__("User not found.")


class AccessRequestNotFoundError(NotFoundError):
    code = "access_request_not_found"

    def __init__(self) -> None:
        super().__init__("Access request not found.")


class LastAdminError(ConflictError):
    code = "last_tenant_admin"


class SelfChangeError(ConflictError):
    code = "cannot_change_yourself"


class InvalidSignupCodeError(DomainError):
    status_code = 422
    code = "invalid_signup_code"


class TooManyAttemptsError(DomainError):
    status_code = 429
    code = "too_many_attempts"


class InvalidApprovalError(DomainError):
    status_code = 422
    code = "invalid_approval"


class EmailNotVerifiedError(ForbiddenError):
    code = "email_not_verified"


def _now() -> datetime:
    return datetime.now(UTC)


def _tenant_id(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can manage its users.")
    return principal.tenant_id


def _audit(
    session: Session,
    principal: Principal,
    action: str,
    entity_id: uuid.UUID,
    changes: dict[str, object],
    entity_type: str = "user",
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
    )


def new_signup_code() -> str:
    chars = "".join(secrets.choice(SIGNUP_CODE_ALPHABET) for _ in range(12))
    return f"{chars[:4]}-{chars[4:8]}-{chars[8:]}"


def _split_name(display_name: str) -> tuple[str, str]:
    first, _, last = display_name.strip().partition(" ")
    return first or display_name, last or "-"


@contextmanager
def _new_login(admin: IdentityAdmin, identity: NewIdentity, roles: frozenset[str]) -> Iterator[str]:
    """Creates the Keycloak login; deletes it again if the block raises."""
    subject = admin.create_user(identity)
    try:
        admin.set_roles(subject, roles)
        yield subject
    except Exception:
        try:
            admin.delete_user(subject)
        except Exception:  # the original error matters more; log the leftover login
            logger.exception("could not remove Keycloak login after a failure")
        raise


def _email_taken(session: Session, tenant_id: uuid.UUID, email: str) -> User | None:
    return session.scalars(
        select(User).where(User.tenant_id == tenant_id, func.lower(User.email) == email.lower())
    ).one_or_none()


def _flush_user(session: Session) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        raise IdentityConflictError(
            "This e-mail address can't be used. It may already belong to an account."
        ) from exc


# --- views --------------------------------------------------------------------------------


def _grants_by_user(session: Session, tenant_id: uuid.UUID) -> dict[uuid.UUID, list[uuid.UUID]]:
    grants: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    rows = session.execute(
        select(PortalAccessGrant.user_id, PortalAccessGrant.account_id).where(
            PortalAccessGrant.tenant_id == tenant_id
        )
    ).all()
    for row in rows:
        grants[row.user_id].append(row.account_id)
    return grants


def _admin_view(user: User, accounts: list[uuid.UUID]) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        user_type="customer" if user.user_type == "customer" else "staff",
        roles=sorted(user.roles or []),
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        portal_account_ids=accounts,
    )


def list_users(session: Session, principal: Principal) -> list[AdminUserRead]:
    tenant_id = _tenant_id(principal)
    users = session.scalars(
        select(User)
        .where(User.tenant_id == tenant_id, User.user_type != "automation")
        .order_by(User.user_type, User.display_name)
    ).all()
    grants = _grants_by_user(session, tenant_id)
    return [_admin_view(u, grants.get(u.id, [])) for u in users]


def _user_view(session: Session, user: User) -> AdminUserRead:
    return _admin_view(user, _grants_by_user(session, user.tenant_id).get(user.id, []))


# --- staff users --------------------------------------------------------------------------


def create_staff_user(
    session: Session,
    principal: Principal,
    admin: IdentityAdmin,
    *,
    issuer: str,
    email: str,
    first_name: str,
    last_name: str,
    role: str,
) -> AdminUserRead:
    tenant_id = _tenant_id(principal)
    if _email_taken(session, tenant_id, email):
        raise IdentityConflictError("Someone in your organisation already uses this e-mail.")
    with _new_login(admin, NewIdentity(email, first_name, last_name), frozenset({role})) as sub:
        user = User(
            tenant_id=tenant_id,
            idp_issuer=issuer,
            idp_subject=sub,
            email=email,
            display_name=f"{first_name} {last_name}",
            user_type="staff",
            roles=[role],
        )
        session.add(user)
        _flush_user(session)
        _audit(session, principal, "user.invited", user.id, {"email": email, "role": role})
        session.flush()
        admin.send_setup_email(sub)
    return _user_view(session, user)


def _load_user(session: Session, principal: Principal, user_id: uuid.UUID) -> User:
    user = session.scalars(
        select(User)
        .where(
            User.tenant_id == _tenant_id(principal),
            User.id == user_id,
            User.user_type != "automation",  # the automation identity is not managed here
        )
        .with_for_update()
    ).one_or_none()
    if user is None:
        raise UserNotFoundError()
    return user


def _active_admin_count(session: Session, tenant_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count()).where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                User.user_type == "staff",
                User.roles.contains([Role.TENANT_ADMIN.value]),
            )
        )
        or 0
    )


def _guard_admin_loss(session: Session, principal: Principal, user: User) -> None:
    if user.id == principal.user_id:
        raise SelfChangeError("You cannot change your own role or deactivate yourself.")
    if Role.TENANT_ADMIN.value in (user.roles or []) and user.is_active:
        if _active_admin_count(session, user.tenant_id) <= 1:
            raise LastAdminError("Your organisation needs at least one active Tenant Admin.")


def change_role(
    session: Session, principal: Principal, admin: IdentityAdmin, user_id: uuid.UUID, role: str
) -> AdminUserRead:
    user = _load_user(session, principal, user_id)
    if user.user_type != "staff":
        raise ConflictError("Customers always have the customer role.")
    previous = list(user.roles or [])
    if previous == [role]:
        return _user_view(session, user)
    if role != Role.TENANT_ADMIN.value:
        _guard_admin_loss(session, principal, user)
    elif user.id == principal.user_id:
        raise SelfChangeError("You cannot change your own role or deactivate yourself.")
    admin.set_roles(user.idp_subject, frozenset({role}))
    user.roles = [role]
    _audit(
        session,
        principal,
        "user.role_changed",
        user.id,
        {"roles": {"old": previous, "new": [role]}},
    )
    session.flush()
    return _user_view(session, user)


def set_active(
    session: Session, principal: Principal, admin: IdentityAdmin, user_id: uuid.UUID, active: bool
) -> AdminUserRead:
    user = _load_user(session, principal, user_id)
    if user.is_active == active:
        return _user_view(session, user)
    if not active:
        _guard_admin_loss(session, principal, user)
    admin.set_enabled(user.idp_subject, active)
    user.is_active = active
    _audit(session, principal, "user.reactivated" if active else "user.deactivated", user.id, {})
    session.flush()
    return _user_view(session, user)


def resend_invite(
    session: Session, principal: Principal, admin: IdentityAdmin, user_id: uuid.UUID
) -> None:
    user = _load_user(session, principal, user_id)
    if not user.is_active:
        raise ConflictError("Reactivate the user first.")
    admin.send_setup_email(user.idp_subject)
    _audit(session, principal, "user.invite_resent", user.id, {})


# --- sign-up code -------------------------------------------------------------------------


def signup_code(session: Session, principal: Principal) -> str:
    tenant = session.get(Tenant, _tenant_id(principal))
    if tenant is None:
        raise ForbiddenError("Organisation not found.")
    return tenant.signup_code


def regenerate_signup_code(session: Session, principal: Principal) -> str:
    tenant = session.get(Tenant, _tenant_id(principal), with_for_update=True)
    if tenant is None:
        raise ForbiddenError("Organisation not found.")
    tenant.signup_code = new_signup_code()
    record_audit(
        session,
        principal,
        action="tenant.signup_code_regenerated",
        entity_type="tenant",
        entity_id=tenant.id,
        changes={},
    )
    session.flush()
    return tenant.signup_code


# --- portal access (customers) ------------------------------------------------------------


def _check_account(session: Session, principal: Principal, account_id: uuid.UUID) -> None:
    """Tenant admins: any account of their tenant. Sales agents: only accounts they own."""
    if principal.user_type != "staff" or not principal.has_permission(
        Permission.PORTAL_USER_INVITE
    ):
        raise ForbiddenError("You may not manage portal access.")
    if principal.has_permission(Permission.TENANT_USER_MANAGE):
        allowed = accounts_api.is_readable_account(session, principal, account_id)
    else:
        allowed = accounts_api.is_owned_account(session, principal, account_id)
    if not allowed:
        raise NotFoundError("Account not found.")


def portal_users(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> list[PortalUserRead]:
    if principal.user_type != "staff" or principal.tenant_id is None:
        raise ForbiddenError("Only staff can see portal access.")
    if not accounts_api.is_readable_account(session, principal, account_id):
        raise NotFoundError("Account not found.")
    users = session.scalars(
        select(User)
        .join(
            PortalAccessGrant,
            (PortalAccessGrant.user_id == User.id)
            & (PortalAccessGrant.tenant_id == User.tenant_id),
        )
        .where(
            PortalAccessGrant.tenant_id == principal.tenant_id,
            PortalAccessGrant.account_id == account_id,
        )
        .order_by(User.display_name)
    ).all()
    return [
        PortalUserRead(
            id=u.id,
            display_name=u.display_name,
            email=u.email,
            is_active=u.is_active,
            last_login_at=u.last_login_at,
        )
        for u in users
    ]


def _grant(session: Session, user: User, account_id: uuid.UUID) -> bool:
    exists = session.scalar(
        select(PortalAccessGrant.id).where(
            PortalAccessGrant.tenant_id == user.tenant_id,
            PortalAccessGrant.user_id == user.id,
            PortalAccessGrant.account_id == account_id,
        )
    )
    if exists:
        return False
    session.add(PortalAccessGrant(tenant_id=user.tenant_id, user_id=user.id, account_id=account_id))
    return True


def invite_portal_user(
    session: Session,
    principal: Principal,
    admin: IdentityAdmin,
    account_id: uuid.UUID,
    *,
    issuer: str,
    email: str,
    first_name: str,
    last_name: str,
) -> PortalUserRead:
    _check_account(session, principal, account_id)
    tenant_id = _tenant_id(principal)
    existing = _email_taken(session, tenant_id, email)
    if existing is not None:
        # Someone already in the portal gets access to one more account - no new login.
        if existing.user_type != "customer":
            raise IdentityConflictError("This e-mail belongs to a staff member.")
        if _grant(session, existing, account_id):
            _audit(
                session, principal, "portal.access_granted", existing.id, {"account_id": account_id}
            )
        session.flush()
        user = existing
    else:
        identity = NewIdentity(email, first_name, last_name)
        with _new_login(admin, identity, frozenset({Role.CUSTOMER.value})) as sub:
            user = User(
                tenant_id=tenant_id,
                idp_issuer=issuer,
                idp_subject=sub,
                email=email,
                display_name=f"{first_name} {last_name}",
                user_type="customer",
                roles=[Role.CUSTOMER.value],
            )
            session.add(user)
            _flush_user(session)
            _grant(session, user, account_id)
            _audit(
                session,
                principal,
                "portal.user_invited",
                user.id,
                {"email": email, "account_id": account_id},
            )
            session.flush()
            admin.send_setup_email(sub)
    return PortalUserRead(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


def revoke_portal_access(
    session: Session, principal: Principal, account_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    _check_account(session, principal, account_id)
    removed = session.execute(
        delete(PortalAccessGrant)
        .where(
            PortalAccessGrant.tenant_id == principal.tenant_id,
            PortalAccessGrant.account_id == account_id,
            PortalAccessGrant.user_id == user_id,
        )
        .returning(PortalAccessGrant.id)
    ).first()
    if removed is None:
        raise UserNotFoundError()
    _audit(session, principal, "portal.access_revoked", user_id, {"account_id": account_id})


# --- access requests (self sign-up) -------------------------------------------------------


def _token_identity(token: VerifiedToken) -> tuple[str | None, bool, str]:
    claims = token.claims
    email = claims.get("email")
    verified = bool(claims.get("email_verified"))
    name = claims.get("name") or " ".join(
        str(p) for p in (claims.get("given_name"), claims.get("family_name")) if p
    )
    return (str(email).lower() if email else None), verified, str(name or email or "New user")


def onboarding_status(session: Session, token: VerifiedToken) -> OnboardingStatus:
    email, verified, _ = _token_identity(token)
    # Both lookups happen before any tenant is known. The functions are the narrow, read-only
    # exceptions from ADR 0009; neither can list rows.
    user = (
        session.execute(
            text(
                "SELECT user_id, tenant_id, is_active FROM identity_lookup_user(:issuer, :subject)"
            ),
            {"issuer": token.issuer, "subject": token.subject},
        )
        .mappings()
        .one_or_none()
    )
    if user is not None:
        state = "member" if user["is_active"] else "disabled"
        return OnboardingStatus(state=state, email=email, email_verified=verified)
    latest = (
        session.execute(
            text("SELECT status, tenant_id FROM access_request_latest(:issuer, :subject)"),
            {"issuer": token.issuer, "subject": token.subject},
        )
        .mappings()
        .one_or_none()
    )
    if latest is not None and latest["status"] == "pending":
        tenant = session.get(Tenant, latest["tenant_id"])
        return OnboardingStatus(
            state="pending",
            email=email,
            email_verified=verified,
            organisation_name=tenant.name if tenant else None,
        )
    if latest is not None and latest["status"] == "rejected":
        return OnboardingStatus(state="rejected", email=email, email_verified=verified)
    return OnboardingStatus(state="none", email=email, email_verified=verified)


def submit_access_request(session: Session, token: VerifiedToken, code: str) -> OnboardingStatus:
    email, verified, name = _token_identity(token)
    if not email or not verified:
        raise EmailNotVerifiedError("Please verify your e-mail address first.")
    status = onboarding_status(session, token)
    if status.state in ("member", "disabled"):
        raise ConflictError("You already have access to the CRM.")
    if status.state == "pending":
        raise ConflictError("Your request is already waiting for approval.")
    since = _now() - timedelta(hours=1)
    attempts = session.scalar(
        select(func.count()).where(
            SignupCodeAttempt.idp_issuer == token.issuer,
            SignupCodeAttempt.idp_subject == token.subject,
            SignupCodeAttempt.created_at > since,
        )
    )
    if (attempts or 0) >= MAX_CODE_ATTEMPTS_PER_HOUR:
        raise TooManyAttemptsError("Too many wrong codes. Please try again in an hour.")
    submitted = (
        session.execute(
            text(
                "SELECT request_id, tenant_id FROM access_request_submit("
                ":issuer, :subject, :email, :display_name, :code)"
            ),
            {
                "issuer": token.issuer,
                "subject": token.subject,
                "email": email,
                "display_name": name[:200],
                "code": code,
            },
        )
        .mappings()
        .one_or_none()
    )
    if submitted is None:
        session.add(SignupCodeAttempt(idp_issuer=token.issuer, idp_subject=token.subject))
        session.flush()
        raise InvalidSignupCodeError(
            "This code is not valid. Please check it with your organisation."
        )
    session.flush()
    return onboarding_status(session, token)


def list_access_requests(session: Session, principal: Principal) -> list[AccessRequestRead]:
    tenant_id = _tenant_id(principal)
    rows = session.scalars(
        select(AccessRequest)
        .where(AccessRequest.tenant_id == tenant_id, AccessRequest.status == "pending")
        .order_by(AccessRequest.created_at)
    ).all()
    return [
        AccessRequestRead(
            id=r.id,
            email=r.email,
            display_name=r.display_name,
            status="pending",
            created_at=r.created_at,
        )
        for r in rows
    ]


def _load_request(session: Session, principal: Principal, request_id: uuid.UUID) -> AccessRequest:
    request = session.scalars(
        select(AccessRequest)
        .where(
            AccessRequest.tenant_id == _tenant_id(principal),
            AccessRequest.id == request_id,
            AccessRequest.status == "pending",
        )
        .with_for_update()
    ).one_or_none()
    if request is None:
        raise AccessRequestNotFoundError()
    return request


def approve_access_request(
    session: Session,
    principal: Principal,
    admin: IdentityAdmin,
    request_id: uuid.UUID,
    *,
    role: str,
    account_ids: Sequence[uuid.UUID],
) -> AdminUserRead:
    request = _load_request(session, principal, request_id)
    customer = role == Role.CUSTOMER.value
    if customer and not account_ids:
        raise InvalidApprovalError("Choose at least one account for a customer.")
    if not customer and account_ids:
        raise InvalidApprovalError("Accounts can only be given to customers.")
    for account_id in account_ids:
        if not accounts_api.is_readable_account(session, principal, account_id):
            raise NotFoundError("Account not found.")
    if _email_taken(session, request.tenant_id, request.email):
        raise IdentityConflictError("Someone in your organisation already uses this e-mail.")
    user = User(
        tenant_id=request.tenant_id,
        idp_issuer=request.idp_issuer,
        idp_subject=request.idp_subject,
        email=request.email,
        display_name=request.display_name,
        user_type="customer" if customer else "staff",
        roles=[role],
    )
    session.add(user)
    _flush_user(session)
    for account_id in dict.fromkeys(account_ids):
        _grant(session, user, account_id)
    request.status = "approved"
    request.decided_at = _now()
    request.decided_by_user_id = principal.user_id
    request.granted_role = role
    _audit(
        session,
        principal,
        "access_request.approved",
        user.id,
        {"email": request.email, "role": role, "account_ids": list(account_ids)},
    )
    session.flush()
    # Last, so a Keycloak failure rolls everything above back (the router does not commit).
    admin.set_roles(request.idp_subject, frozenset({role}))
    return _user_view(session, user)


def reject_access_request(session: Session, principal: Principal, request_id: uuid.UUID) -> None:
    request = _load_request(session, principal, request_id)
    request.status = "rejected"
    request.decided_at = _now()
    request.decided_by_user_id = principal.user_id
    _audit(
        session,
        principal,
        "access_request.rejected",
        request.id,
        {"email": request.email},
        entity_type="access_request",
    )
    session.flush()


# --- platform (super admin) ---------------------------------------------------------------


def create_tenant(
    session: Session,
    principal: Principal,
    admin: IdentityAdmin,
    *,
    issuer: str,
    slug: str,
    name: str,
    admin_email: str,
    admin_first_name: str,
    admin_last_name: str,
) -> tuple[Tenant, User]:
    """A new organisation with its first Tenant Admin. Super Admin still sees none of its data."""
    if principal.user_type != "platform" or not principal.has_permission(
        Permission.PLATFORM_TENANT_MANAGE
    ):
        raise ForbiddenError("Only platform administrators can create organisations.")
    if session.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        raise ConflictError("An organisation with this short name already exists.")
    tenant = Tenant(slug=slug, name=name, signup_code=new_signup_code())
    session.add(tenant)
    session.flush()
    identity = NewIdentity(admin_email, admin_first_name, admin_last_name)
    with _new_login(admin, identity, frozenset({Role.TENANT_ADMIN.value})) as sub:
        user = User(
            tenant_id=tenant.id,
            idp_issuer=issuer,
            idp_subject=sub,
            email=admin_email,
            display_name=f"{admin_first_name} {admin_last_name}",
            user_type="staff",
            roles=[Role.TENANT_ADMIN.value],
        )
        session.add(user)
        _flush_user(session)
        # Audit rows belong to a tenant: record it in the new tenant, by the platform user.
        _audit(
            session,
            replace(principal, tenant_id=tenant.id),
            "tenant.created",
            tenant.id,
            {"slug": slug, "first_admin": admin_email},
            entity_type="tenant",
        )
        session.flush()
        admin.send_setup_email(sub)
    return tenant, user
