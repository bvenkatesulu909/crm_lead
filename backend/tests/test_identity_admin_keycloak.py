"""The real Keycloak admin client against the local Keycloak + Mailpit (docker compose).

Creates a throw-away login, gives it a role, checks the set-your-password e-mail arrives in
Mailpit, disables it and deletes it again. Skipped when Keycloak, Mailpit or the admin client
secret (CRM_KEYCLOAK_ADMIN_CLIENT_SECRET in backend/.env) are not available.
"""

import time
import uuid
from collections.abc import Iterator

import httpx
import pytest

from app.core.auth.identity_admin import (
    IdentityConflictError,
    KeycloakIdentityAdmin,
    NewIdentity,
)
from app.core.config import Settings

MAILPIT = "http://localhost:8025/api/v1"


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        settings = Settings()  # reads backend/.env
    except Exception:
        pytest.skip("backend/.env not configured")
    if settings.keycloak_admin_client_secret is None:
        pytest.skip("CRM_KEYCLOAK_ADMIN_CLIENT_SECRET not set")
    try:
        httpx.get(f"{settings.oidc_issuer}/.well-known/openid-configuration", timeout=3)
        httpx.get(f"{MAILPIT}/messages", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Keycloak or Mailpit is not running")
    return settings


@pytest.fixture
def admin(settings: Settings) -> KeycloakIdentityAdmin:
    return KeycloakIdentityAdmin(settings)


@pytest.fixture
def login(admin: KeycloakIdentityAdmin) -> Iterator[tuple[str, str]]:
    email = f"it-{uuid.uuid4().hex[:10]}@example.test"
    subject = admin.create_user(NewIdentity(email, "Integration", "Test"))
    yield subject, email
    admin.delete_user(subject)


def _realm_roles(admin: KeycloakIdentityAdmin, subject: str) -> set[str]:
    response = admin._request("GET", f"/users/{subject}/role-mappings/realm")
    return {r["name"] for r in response.json()}


def test_roles_are_replaced_not_added(admin, login) -> None:
    subject, _ = login

    admin.set_roles(subject, frozenset({"sales_agent"}))
    assert {"sales_agent"} <= _realm_roles(admin, subject)
    admin.set_roles(subject, frozenset({"support_agent"}))
    roles = _realm_roles(admin, subject)

    assert "support_agent" in roles and "sales_agent" not in roles


def test_super_admin_can_never_be_given(admin, login) -> None:
    with pytest.raises(ValueError, match="super_admin"):
        admin.set_roles(login[0], frozenset({"super_admin"}))


def test_invitation_email_arrives_in_mailpit(admin, login) -> None:
    subject, email = login

    admin.send_setup_email(subject)

    for _ in range(20):
        found = httpx.get(f"{MAILPIT}/search", params={"query": f"to:{email}"}).json()
        if found["messages_count"]:
            break
        time.sleep(0.5)
    assert found["messages_count"] == 1
    message = httpx.get(f"{MAILPIT}/message/{found['messages'][0]['ID']}").json()
    assert "action-token" in message["Text"] or "action-token" in message["HTML"]


def test_same_email_twice_is_a_conflict(admin, login) -> None:
    with pytest.raises(IdentityConflictError):
        admin.create_user(NewIdentity(login[1], "Again", "Same"))


def test_disable_and_enable(admin, login) -> None:
    subject, _ = login

    admin.set_enabled(subject, False)
    assert admin._request("GET", f"/users/{subject}").json()["enabled"] is False
    admin.set_enabled(subject, True)
    assert admin._request("GET", f"/users/{subject}").json()["enabled"] is True
