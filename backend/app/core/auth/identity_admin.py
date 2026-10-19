"""Managing login identities in Keycloak (ADR 0004).

The backend uses the confidential client "crm-user-admin", whose service account may only
manage USERS of the CRM realm (no realm settings, no other realms). The browser never talks
to this API.

``IdentityAdmin`` is a Protocol, so tests use an in-memory fake and production uses
``KeycloakIdentityAdmin``. Passwords never pass through the CRM: new people get a
"set your password" e-mail from Keycloak (caught by Mailpit locally).
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import DomainError

logger = logging.getLogger(__name__)

# Roles the CRM may hand out. super_admin is deliberately absent: it can never be granted here.
ASSIGNABLE_REALM_ROLES = frozenset(
    {"tenant_admin", "sales_manager", "sales_agent", "support_agent", "customer"}
)


class IdentityAdminUnavailableError(DomainError):
    status_code = 503
    code = "identity_admin_unavailable"


class IdentityConflictError(DomainError):
    status_code = 409
    code = "email_in_use"


@dataclass(frozen=True)
class NewIdentity:
    email: str
    first_name: str
    last_name: str


class IdentityAdmin(Protocol):
    def create_user(self, identity: NewIdentity) -> str:
        """Create a login without a password; returns its subject (Keycloak user id)."""
        ...

    def delete_user(self, subject: str) -> None: ...

    def set_roles(self, subject: str, roles: frozenset[str]) -> None:
        """Make ``roles`` the person's CRM roles (other CRM roles are removed)."""
        ...

    def set_enabled(self, subject: str, enabled: bool) -> None:
        """Disabling also ends all of the person's sessions."""
        ...

    def send_setup_email(self, subject: str) -> None:
        """E-mail with a link to verify the address and set a password."""
        ...


class KeycloakIdentityAdmin:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if settings.keycloak_admin_client_secret is None:
            raise ValueError("keycloak_admin_client_secret is not configured")
        self._settings = settings
        self._secret = settings.keycloak_admin_client_secret
        self._base = f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}"
        self._token_url = f"{settings.oidc_issuer}/protocol/openid-connect/token"
        self._http = client or httpx.Client(timeout=10)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires = 0.0

    # --- plumbing -----------------------------------------------------------------------

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._token_expires - 30:
                return self._token
            try:
                response = self._http.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._settings.keycloak_admin_client_id,
                        "client_secret": self._secret.get_secret_value(),
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "cannot get a Keycloak admin token", extra={"error": type(exc).__name__}
                )
                raise IdentityAdminUnavailableError(
                    "User administration is temporarily unavailable."
                ) from exc
            body = response.json()
            self._token = str(body["access_token"])
            self._token_expires = time.monotonic() + float(body.get("expires_in", 60))
            return self._token

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            response = self._http.request(
                method,
                f"{self._base}{path}",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                **kwargs,  # type: ignore[arg-type]
            )
        except httpx.HTTPError as exc:
            logger.warning("Keycloak admin call failed", extra={"path": path})
            raise IdentityAdminUnavailableError(
                "User administration is temporarily unavailable."
            ) from exc
        if response.status_code >= 500 or response.status_code in (401, 403):
            logger.warning(
                "Keycloak admin call refused", extra={"path": path, "status": response.status_code}
            )
            raise IdentityAdminUnavailableError("User administration is temporarily unavailable.")
        return response

    # --- operations ---------------------------------------------------------------------

    def create_user(self, identity: NewIdentity) -> str:
        response = self._request(
            "POST",
            "/users",
            json={
                "username": identity.email.lower(),
                "email": identity.email.lower(),
                "firstName": identity.first_name,
                "lastName": identity.last_name,
                "enabled": True,
                "emailVerified": False,
                "requiredActions": ["VERIFY_EMAIL", "UPDATE_PASSWORD"],
            },
        )
        if response.status_code == 409:
            raise IdentityConflictError(
                "This e-mail address can't be used. It may already belong to an account."
            )
        if response.status_code != 201:
            raise IdentityAdminUnavailableError("The login could not be created.")
        # Keycloak answers with the new user's URL: .../users/<id>
        return response.headers["Location"].rstrip("/").rsplit("/", 1)[1]

    def delete_user(self, subject: str) -> None:
        self._request("DELETE", f"/users/{subject}")

    def _realm_roles(self, names: frozenset[str]) -> list[dict[str, object]]:
        # The list endpoint needs only the rights the service account has ("view-users");
        # fetching one role by name would need realm-level rights it deliberately lacks.
        available = {r["name"]: r for r in self._request("GET", "/roles").json()}
        missing = names - available.keys()
        if missing:
            raise IdentityAdminUnavailableError(f"Roles missing in Keycloak: {sorted(missing)}")
        return [available[name] for name in sorted(names)]

    def set_roles(self, subject: str, roles: frozenset[str]) -> None:
        unknown = roles - ASSIGNABLE_REALM_ROLES
        if unknown:
            raise ValueError(f"roles cannot be assigned from the CRM: {sorted(unknown)}")
        current = self._request("GET", f"/users/{subject}/role-mappings/realm").json()
        current_crm = {r["name"] for r in current if r["name"] in ASSIGNABLE_REALM_ROLES}
        remove = frozenset(current_crm - roles)
        add = frozenset(roles - current_crm)
        if remove:
            self._request(
                "DELETE", f"/users/{subject}/role-mappings/realm", json=self._realm_roles(remove)
            )
        if add:
            self._request(
                "POST", f"/users/{subject}/role-mappings/realm", json=self._realm_roles(add)
            )

    def set_enabled(self, subject: str, enabled: bool) -> None:
        self._request("PUT", f"/users/{subject}", json={"enabled": enabled})
        if not enabled:
            self._request("POST", f"/users/{subject}/logout")

    def send_setup_email(self, subject: str) -> None:
        user = self._request("GET", f"/users/{subject}").json()
        actions = ["UPDATE_PASSWORD"]
        if not user.get("emailVerified"):
            actions.insert(0, "VERIFY_EMAIL")
        response = self._request(
            "PUT",
            f"/users/{subject}/execute-actions-email",
            params={
                "client_id": "crm-web",
                "redirect_uri": f"{self._settings.web_app_url}/login",
                "lifespan": self._settings.invite_link_lifespan_seconds,
            },
            json=actions,
        )
        if response.status_code not in (200, 204):
            raise IdentityAdminUnavailableError("The invitation e-mail could not be sent.")


class UnconfiguredIdentityAdmin:
    """Used when no admin client secret is set: every operation answers 503."""

    def _fail(self) -> None:
        raise IdentityAdminUnavailableError(
            "User administration is not configured (CRM_KEYCLOAK_ADMIN_CLIENT_SECRET)."
        )

    def create_user(self, identity: NewIdentity) -> str:
        self._fail()
        return ""

    def delete_user(self, subject: str) -> None:
        self._fail()

    def set_roles(self, subject: str, roles: frozenset[str]) -> None:
        self._fail()

    def set_enabled(self, subject: str, enabled: bool) -> None:
        self._fail()

    def send_setup_email(self, subject: str) -> None:
        self._fail()


def build_identity_admin(settings: Settings) -> IdentityAdmin:
    if settings.keycloak_admin_client_secret is None:
        return UnconfiguredIdentityAdmin()
    return KeycloakIdentityAdmin(settings)
