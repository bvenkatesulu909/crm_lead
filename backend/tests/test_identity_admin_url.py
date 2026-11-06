"""Where the API sends its Keycloak administration calls.

Found on the first real server (D2 staging, 2026-11-06): the one-server proxy closes
https://login.../admin* to the internet (ADR 0021), so the API - which used the public sign-in
address for its admin calls - got 403 and creating an organisation failed with 503. The API must
be able to send its admin calls to Keycloak inside the server instead, while tokens keep coming
from the public issuer (the address in every token).
"""

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.auth.identity_admin import KeycloakIdentityAdmin, NewIdentity
from app.core.config import Settings
from tests.conftest import UNREACHABLE_DATABASE_URL

ISSUER = "https://login.example.test/realms/crm"


def settings(identity_admin_url: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=ISSUER,
        keycloak_admin_client_secret=SecretStr("x" * 32),
        identity_admin_url=identity_admin_url,
    )


def recorded_calls(admin_settings: Settings) -> list[str]:
    calls: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url}")
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
        return httpx.Response(201, headers={"Location": f"{request.url}/abc"})

    client = httpx.Client(transport=httpx.MockTransport(answer))
    KeycloakIdentityAdmin(admin_settings, client).create_user(NewIdentity("a@b.test", "A", "B"))
    return calls


def test_admin_calls_go_to_the_internal_address_when_one_is_set() -> None:
    calls = recorded_calls(settings(identity_admin_url="http://keycloak:8080"))
    assert calls[0] == f"POST {ISSUER}/protocol/openid-connect/token"
    assert calls[1] == "POST http://keycloak:8080/admin/realms/crm/users"


def test_without_an_internal_address_admin_calls_use_the_issuer_host() -> None:
    calls = recorded_calls(settings())
    assert calls[1] == "POST https://login.example.test/admin/realms/crm/users"


@pytest.mark.parametrize(
    "bad", ["keycloak:8080", "http://keycloak:8080/", "ftp://keycloak", "http://"]
)
def test_the_internal_address_must_be_a_plain_absolute_url(bad: str) -> None:
    with pytest.raises(ValidationError):
        settings(identity_admin_url=bad)
