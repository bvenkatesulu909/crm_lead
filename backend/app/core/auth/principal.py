"""The Principal: who is making this request, as established by the server.

It is built only from a verified access token plus the CRM's own database. Nothing in it
comes from request bodies, query strings or custom headers, so a client cannot claim to be
another user or to belong to another tenant.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from app.core.auth.rbac import Permission, Role

UserType = Literal["platform", "staff", "customer"]


@dataclass(frozen=True)
class Principal:
    subject: str  # Keycloak "sub"
    issuer: str  # Keycloak "iss"
    user_type: UserType
    roles: frozenset[Role]
    permissions: frozenset[Permission]
    # None only for platform users (super admins), who belong to no tenant.
    user_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    # From the CRM user record, for display only (never used for authorization).
    display_name: str | None = None
    email: str | None = None
    tenant_name: str | None = None

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions
