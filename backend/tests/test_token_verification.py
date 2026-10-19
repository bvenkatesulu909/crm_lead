"""Access-token validation: every way a token can be wrong must be rejected.

These tests need no database: a bad token is rejected before the database is touched.
"""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.auth.tokens import InvalidTokenError
from tests.auth_helpers import (
    TEST_AUDIENCE,
    TEST_ISSUER,
    TokenFactory,
    bearer,
    forge_token,
    hs256_signed_with_public_key,
    tamper_payload,
)

PROTECTED_ENDPOINTS = ["/api/v1/me", "/api/v1/accounts", "/api/v1/portal/accounts"]


# --- Unit tests on the verifier itself -------------------------------------------------


def test_valid_token_is_accepted(token_factory: TokenFactory) -> None:
    verified = token_factory.verifier().verify(token_factory.mint("user-1", ["sales_agent"]))

    assert verified.subject == "user-1"
    assert verified.issuer == TEST_ISSUER
    assert verified.roles == frozenset({"sales_agent"})


def _bad_tokens(factory: TokenFactory) -> dict[str, str]:
    now = int(time.time())
    attacker = TokenFactory(kid=factory.kid)  # same key id, different private key

    def without(claim: str) -> dict[str, Any]:
        reduced = factory.claims("user-1")
        reduced.pop(claim)
        return reduced

    return {
        "signed by another key": attacker.mint("user-1"),
        "expired": factory.sign(factory.claims("user-1", exp=now - 120, iat=now - 600)),
        "not valid yet (nbf)": factory.sign(factory.claims("user-1", nbf=now + 600)),
        "issued in the future (iat)": factory.sign(factory.claims("user-1", iat=now + 600)),
        "wrong issuer": factory.sign(factory.claims("user-1", iss="http://evil.test/realms/crm")),
        "wrong audience": factory.sign(factory.claims("user-1", aud="some-other-api")),
        "missing audience": factory.sign(without("aud")),
        "missing expiry": factory.sign(without("exp")),
        "missing subject": factory.sign(without("sub")),
        "empty subject": factory.sign(factory.claims("")),
        "ID token, not access token": factory.sign(factory.claims("user-1", typ="ID")),
        "unknown key id": factory.sign(factory.claims("user-1"), kid="unknown-key"),
        "alg=none (unsigned)": forge_token({"alg": "none", "typ": "JWT"}, factory.claims("user-1")),
        "HS256 with public key as secret": hs256_signed_with_public_key(
            factory, factory.claims("user-1", realm_access={"roles": ["tenant_admin"]})
        ),
        "roles changed after signing": tamper_payload(
            factory.mint("user-1", ["sales_agent"]), realm_access={"roles": ["tenant_admin"]}
        ),
        "subject changed after signing": tamper_payload(factory.mint("user-1"), sub="user-2"),
        "not a JWT": "definitely-not-a-jwt",
    }


@pytest.fixture(scope="module")
def bad_tokens(token_factory: TokenFactory) -> dict[str, str]:
    return _bad_tokens(token_factory)


BAD_TOKEN_CASES = [
    "signed by another key",
    "expired",
    "not valid yet (nbf)",
    "issued in the future (iat)",
    "wrong issuer",
    "wrong audience",
    "missing audience",
    "missing expiry",
    "missing subject",
    "empty subject",
    "ID token, not access token",
    "unknown key id",
    "alg=none (unsigned)",
    "HS256 with public key as secret",
    "roles changed after signing",
    "subject changed after signing",
    "not a JWT",
]


@pytest.mark.parametrize("case", BAD_TOKEN_CASES)
def test_verifier_rejects_bad_token(
    case: str, token_factory: TokenFactory, bad_tokens: dict[str, str]
) -> None:
    assert set(bad_tokens) == set(BAD_TOKEN_CASES)
    with pytest.raises(InvalidTokenError):
        token_factory.verifier().verify(bad_tokens[case])


def test_small_clock_skew_is_tolerated(token_factory: TokenFactory) -> None:
    now = int(time.time())
    token = token_factory.sign(token_factory.claims("user-1", exp=now - 10, iat=now - 300))

    assert token_factory.verifier().verify(token).subject == "user-1"


def test_audience_may_be_a_list_containing_crm_api(token_factory: TokenFactory) -> None:
    token = token_factory.sign(token_factory.claims("user-1", aud=["account", TEST_AUDIENCE]))

    assert token_factory.verifier().verify(token).subject == "user-1"


# --- The same checks through HTTP ------------------------------------------------------


@pytest.mark.parametrize("path", PROTECTED_ENDPOINTS)
def test_missing_token_returns_401_with_bearer_challenge(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer ", "Token abc", "bearer-without-space"]
)
def test_malformed_authorization_header_returns_401(client: TestClient, header: str) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": header})

    assert response.status_code == 401


@pytest.mark.parametrize("case", BAD_TOKEN_CASES)
def test_bad_token_returns_generic_401(
    case: str, client: TestClient, bad_tokens: dict[str, str]
) -> None:
    token = bad_tokens[case]
    response = client.get("/api/v1/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    # Same message for every failure, and the token is never echoed back.
    assert response.json()["detail"] == "Missing or invalid access token."
    assert token not in response.text
