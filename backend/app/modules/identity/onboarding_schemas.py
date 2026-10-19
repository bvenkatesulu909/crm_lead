"""Request/response contracts for user administration and onboarding (ADR 0004).

The organisation of a new user is never part of a request: it is always the admin's own.
Super Admin can never be requested; staff roles are a closed list.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")


def _email(value: str) -> str:
    if not _EMAIL.fullmatch(value):
        raise ValueError("must be a valid e-mail address")
    # Logins are matched case-insensitively, so addresses are stored in lower case.
    return value.lower()


EmailStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=320),
    AfterValidator(_email),
]
StaffRole = Literal["tenant_admin", "sales_manager", "sales_agent", "support_agent"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Code = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=4, max_length=20)
]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=63)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaffUserCreate(_Input):
    email: EmailStr
    first_name: Name
    last_name: Name
    role: StaffRole


class RoleChange(_Input):
    role: StaffRole


class PortalInvite(_Input):
    email: EmailStr
    first_name: Name
    last_name: Name


class AccessRequestApproval(_Input):
    """Either a staff role, or "customer" with the accounts the person may see."""

    role: StaffRole | Literal["customer"]
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class SignupRequest(_Input):
    signup_code: Code


class TenantCreate(_Input):
    slug: Slug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    admin_email: EmailStr
    admin_first_name: Name
    admin_last_name: Name


class AdminUserRead(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    user_type: Literal["staff", "customer"]
    roles: list[str]
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    portal_account_ids: list[uuid.UUID]


class SignupCodeRead(BaseModel):
    signup_code: str


class AccessRequestRead(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime


class PortalUserRead(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    is_active: bool
    last_login_at: datetime | None


OnboardingState = Literal["member", "disabled", "pending", "rejected", "none"]


class OnboardingStatus(BaseModel):
    state: OnboardingState
    email: str | None
    email_verified: bool
    organisation_name: str | None = Field(
        default=None, description="Only while a request is pending (the person entered its code)."
    )


class TenantCreated(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    signup_code: str
    admin_user_id: uuid.UUID
