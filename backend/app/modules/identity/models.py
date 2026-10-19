"""Identity tables: ``tenants``, ``users`` and ``portal_access_grants``.

Passwords are NOT stored here: Keycloak handles login. ``users`` only links a Keycloak
identity (issuer + subject from the token) to a CRM user inside exactly one tenant.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

TENANT_STATUSES = ("active", "suspended")
# "automation": one per tenant, used by workflow rules (ADR 0006). It has no Keycloak account,
# so nobody can sign in as it, and it never appears among colleagues.
USER_TYPES = ("staff", "customer", "automation")
ACCESS_REQUEST_STATUSES = ("pending", "approved", "rejected")
# Sign-up codes: 3 groups of 4 from an alphabet without look-alikes (0/O, 1/I/L).
SIGNUP_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
SIGNUP_CODE_PATTERN = "^[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}$"


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A company using the CRM. Root of all data ownership; not owned by anything itself."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug"),
        UniqueConstraint("signup_code"),
        CheckConstraint(f"signup_code ~ '{SIGNUP_CODE_PATTERN}'", name="signup_code_format"),
        # Lower-case words separated by single hyphens, e.g. "acme-demo".
        CheckConstraint(r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint(f"status IN {TENANT_STATUSES}", name="status_allowed"),
    )

    slug: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'active'"))
    # Given by the organisation's admins to people who sign up themselves (ADR 0004). Random,
    # not derived from the name, so organisations cannot be guessed or listed.
    # The database fills it in (crm_new_signup_code(), migration 0008).
    signup_code: Mapped[str] = mapped_column(
        String(14), server_default=text("crm_new_signup_code()")
    )


class User(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    """A person who can sign in: staff member or customer-portal user, in one tenant."""

    __tablename__ = "users"
    __table_args__ = (
        # Target for composite foreign keys from other tables (same-tenant guarantee).
        UniqueConstraint("tenant_id", "id"),
        # Lets portal_access_grants require "this user is a customer" in a foreign key.
        UniqueConstraint("tenant_id", "id", "user_type"),
        # A Keycloak identity maps to exactly ONE CRM user, so the tenant of a request is
        # fully determined by the verified token - the client never chooses it.
        UniqueConstraint("idp_issuer", "idp_subject"),
        # E-mail addresses are unique per tenant, ignoring upper/lower case.
        Index(
            "uq_users_tenant_id_lower_email", "tenant_id", func.lower(text("email")), unique=True
        ),
        CheckConstraint(f"user_type IN {USER_TYPES}", name="user_type_allowed"),
    )

    # "iss" and "sub" claims of the Keycloak token: together they identify the person.
    idp_issuer: Mapped[str] = mapped_column(String(255))
    idp_subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    user_type: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)
    # Last CRM roles seen in this user's token (refreshed at every sign-in). Used only to decide
    # who may RECEIVE work (e.g. lead assignment); access itself is always checked on the
    # live token, so a stale snapshot can never grant access.
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(30)), server_default=text("'{}'"))


class PortalAccessGrant(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """Allows one customer-portal user to see one customer account.

    The database guarantees that the user is a *customer* of the *same tenant* as the account.
    """

    __tablename__ = "portal_access_grants"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "account_id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id", "user_type"],
            ["users.tenant_id", "users.id", "users.user_type"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="CASCADE"
        ),
        CheckConstraint("user_type = 'customer'", name="customer_only"),
        Index("ix_portal_access_grants_tenant_id_account_id", "tenant_id", "account_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # Always 'customer'; part of the foreign key so a staff user can never get a grant.
    user_type: Mapped[str] = mapped_column(String(20), server_default=text("'customer'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AccessRequest(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    """Someone who signed up in Keycloak and asks to join an organisation (ADR 0004).

    Identity, e-mail and name come from the verified token, never from what the person typed.
    Until an admin approves, the person has no CRM user and therefore no access to any data.
    """

    __tablename__ = "access_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "decided_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {ACCESS_REQUEST_STATUSES}", name="status_allowed"),
        CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="decision_consistent"),
        # One open request per identity at a time.
        Index(
            "uq_access_requests_identity_pending",
            "idp_issuer",
            "idp_subject",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_access_requests_tenant_id_status", "tenant_id", "status"),
    )

    idp_issuer: Mapped[str] = mapped_column(String(255))
    idp_subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    # What was granted: a staff role name or "customer".
    granted_role: Mapped[str | None] = mapped_column(String(30))


class SignupCodeAttempt(UUIDPrimaryKeyMixin, Base):
    """A wrong sign-up code entered by someone (for the 5-per-hour limit). Not tenant data."""

    __tablename__ = "signup_code_attempts"
    __table_args__ = (
        Index(
            "ix_signup_code_attempts_identity_created_at", "idp_issuer", "idp_subject", "created_at"
        ),
    )

    idp_issuer: Mapped[str] = mapped_column(String(255))
    idp_subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
