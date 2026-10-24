"""End-to-end checks against the REAL local Keycloak (docker compose service "keycloak").

Performs the same Authorization Code + PKCE login the web app will do: open the login page,
submit username/password, receive a one-time code, exchange it (with the PKCE verifier and the
client secret) for tokens. Then calls the API with the real access token.

Skipped when Keycloak is not running or the test credentials are not configured in backend/.env:
    CRM_TEST_KEYCLOAK_WEB_CLIENT_SECRET, CRM_TEST_KEYCLOAK_USER_PASSWORD
"""

import base64
import hashlib
import html
import re
import secrets
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.core.auth.tokens import InvalidTokenError, JwksKeyProvider, TokenVerifier
from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity.models import Tenant, User
from tests.auth_helpers import bearer, tamper_payload
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import BACKEND_DIR, session_factory_for

ISSUER = "http://localhost:9080/realms/crm"
OIDC = f"{ISSUER}/protocol/openid-connect"
CLIENT_ID = "crm-web"
REDIRECT_URI = "http://localhost:3000/api/auth/callback/keycloak"
AGENT1_SUBJECT = "a1000000-0000-4000-8000-000000000003"  # alpha.agent1 in realm-crm.json


class KeycloakTestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRM_TEST_KEYCLOAK_", env_file=BACKEND_DIR / ".env", extra="ignore"
    )

    web_client_secret: SecretStr | None = None
    user_password: SecretStr | None = None


@pytest.fixture(scope="module")
def kc() -> KeycloakTestSettings:
    settings = KeycloakTestSettings()
    if settings.web_client_secret is None or settings.user_password is None:
        pytest.skip("Keycloak test credentials not configured in backend/.env")
    try:
        httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Keycloak is not running on localhost:9080")
    return settings


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def _authorize(
    browser: httpx.Client, username: str, password: str, **params: str
) -> dict[str, list[str]]:
    """Log in through Keycloak's login page; return the query parameters of the redirect."""
    query = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": REDIRECT_URI,
        "state": secrets.token_urlsafe(16),
        **params,
    }
    page = browser.get(f"{OIDC}/auth?{urlencode(query)}")
    if page.status_code == 302:  # Keycloak refused before showing the login page
        return parse_qs(urlsplit(page.headers["location"]).query)
    match = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
    assert match, "Keycloak login form not found"
    # Keycloak marks its login cookies "Secure". Browsers still send them to http://localhost
    # (they treat localhost as a secure origin); httpx does not, so we send them as a browser would.
    cookies = "; ".join(f"{name}={value}" for name, value in browser.cookies.items())
    result = browser.post(
        html.unescape(match.group(1)),
        data={"username": username, "password": password},
        headers={"Cookie": cookies},
    )
    assert result.status_code == 302, "login was not accepted"
    location = result.headers["location"]
    assert location.startswith(REDIRECT_URI)
    return parse_qs(urlsplit(location).query)


def _exchange(kc: KeycloakTestSettings, code: str, verifier: str | None) -> httpx.Response:
    assert kc.web_client_secret is not None
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": kc.web_client_secret.get_secret_value(),
    }
    if verifier is not None:
        data["code_verifier"] = verifier
    return httpx.post(f"{OIDC}/token", data=data, timeout=10)


def login(kc: KeycloakTestSettings, username: str) -> dict[str, Any]:
    assert kc.user_password is not None
    verifier, challenge = _pkce_pair()
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        params = _authorize(
            browser,
            username,
            kc.user_password.get_secret_value(),
            code_challenge=challenge,
            code_challenge_method="S256",
        )
    response = _exchange(kc, params["code"][0], verifier)
    assert response.status_code == 200, response.text
    tokens: dict[str, Any] = response.json()
    return tokens


@pytest.fixture(scope="module")
def real_verifier() -> TokenVerifier:
    return TokenVerifier(
        issuer=ISSUER, audience="crm-api", key_provider=JwksKeyProvider(f"{OIDC}/certs")
    )


# --- Keycloak client configuration ------------------------------------------------------


def test_pkce_login_returns_access_token_for_crm_api(kc, real_verifier) -> None:
    tokens = login(kc, "alpha.agent1")

    verified = real_verifier.verify(tokens["access_token"])
    assert verified.subject == AGENT1_SUBJECT
    assert verified.roles == frozenset({"sales_agent"})  # only CRM roles, nothing else
    assert "crm-api" in verified.claims["aud"]
    assert verified.claims["azp"] == CLIENT_ID


def test_login_without_pkce_is_refused(kc) -> None:
    assert kc.user_password is not None
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        params = _authorize(browser, "alpha.agent1", kc.user_password.get_secret_value())

    assert params["error"] == ["invalid_request"]
    assert "code" not in params


def test_plain_pkce_method_is_refused(kc) -> None:
    assert kc.user_password is not None
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        params = _authorize(
            browser,
            "alpha.agent1",
            kc.user_password.get_secret_value(),
            code_challenge="a" * 43,
            code_challenge_method="plain",
        )

    assert params["error"] == ["invalid_request"]


@pytest.mark.parametrize("verifier", [None, "wrong-verifier-" + "x" * 50])
def test_code_cannot_be_exchanged_without_the_right_pkce_verifier(kc, verifier) -> None:
    assert kc.user_password is not None
    _, challenge = _pkce_pair()
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        params = _authorize(
            browser,
            "alpha.agent1",
            kc.user_password.get_secret_value(),
            code_challenge=challenge,
            code_challenge_method="S256",
        )

    response = _exchange(kc, params["code"][0], verifier)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_password_grant_is_disabled(kc) -> None:
    assert kc.web_client_secret is not None and kc.user_password is not None
    response = httpx.post(
        f"{OIDC}/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": kc.web_client_secret.get_secret_value(),
            "username": "alpha.agent1",
            "password": kc.user_password.get_secret_value(),
        },
        timeout=10,
    )

    assert response.status_code in (400, 401)
    assert response.json()["error"] == "unauthorized_client"


def test_wrong_client_secret_cannot_exchange_code(kc) -> None:
    assert kc.user_password is not None
    verifier, challenge = _pkce_pair()
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        params = _authorize(
            browser,
            "alpha.agent1",
            kc.user_password.get_secret_value(),
            code_challenge=challenge,
            code_challenge_method="S256",
        )
    wrong = KeycloakTestSettings(
        web_client_secret=SecretStr(secrets.token_urlsafe(32)),  # random, so certainly wrong
        user_password=kc.user_password,
    )

    response = _exchange(wrong, params["code"][0], verifier)
    assert response.status_code == 401


def test_id_token_is_not_accepted_as_access_token(kc, real_verifier) -> None:
    tokens = login(kc, "alpha.agent1")

    with pytest.raises(InvalidTokenError):
        real_verifier.verify(tokens["id_token"])


def test_modified_real_token_is_rejected(kc, real_verifier) -> None:
    token = login(kc, "alpha.agent1")["access_token"]
    forged = tamper_payload(token, realm_access={"roles": ["tenant_admin"]})

    with pytest.raises(InvalidTokenError):
        real_verifier.verify(forged)


# --- Real token -> API -> database ------------------------------------------------------


@pytest.fixture
def real_api(db_connection: Connection, real_verifier: TokenVerifier) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=ISSUER,
    )
    app = create_app(settings, token_verifier=real_verifier)
    app.state.session_factory = session_factory_for(db_connection)
    with TestClient(app) as client:
        yield client


def test_real_keycloak_token_gets_only_own_records(kc, real_api, committed_world: Session) -> None:
    tenant = Tenant(slug="kc-it", name="Keycloak Integration Tenant")
    committed_world.add(tenant)
    committed_world.flush()
    agent = User(
        id=uuid.UUID(AGENT1_SUBJECT),
        tenant_id=tenant.id,
        idp_issuer=ISSUER,
        idp_subject=AGENT1_SUBJECT,
        email="agent1@kc-it.example.test",
        display_name="Agent One",
        user_type="staff",
    )
    committed_world.add(agent)
    committed_world.flush()
    mine = Account(tenant_id=tenant.id, name="Mine", owner_id=agent.id)
    not_mine = Account(tenant_id=tenant.id, name="Not mine", owner_id=None)
    committed_world.add_all([mine, not_mine])
    committed_world.commit()

    headers = bearer(login(kc, "alpha.agent1")["access_token"])

    listed = real_api.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()["items"]] == [str(mine.id)]
    assert real_api.get(f"/api/v1/accounts/{not_mine.id}", headers=headers).status_code == 404
    assert real_api.get("/api/v1/portal/accounts", headers=headers).status_code == 403
