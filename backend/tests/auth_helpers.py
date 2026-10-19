"""Test token issuer: a throw-away RSA key pair that signs access tokens like Keycloak does.

The app under test verifies these tokens with the normal TokenVerifier (same algorithm, issuer,
audience, expiry and signature rules); it is only told to trust this key instead of Keycloak's.
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterable, Mapping
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.auth.tokens import StaticKeyProvider, TokenVerifier

TEST_ISSUER = "http://issuer.test/realms/crm"
TEST_AUDIENCE = "crm-api"


class TokenFactory:
    def __init__(self, kid: str = "test-key-1") -> None:
        self.kid = kid
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        jwk.update(kid=self.kid, alg="RS256", use="sig")
        return {"keys": [jwk]}

    def verifier(self) -> TokenVerifier:
        return TokenVerifier(
            issuer=TEST_ISSUER, audience=TEST_AUDIENCE, key_provider=StaticKeyProvider(self.jwks())
        )

    def claims(
        self,
        subject: str = "test-subject",
        roles: Iterable[str] = (),
        *,
        lifetime_seconds: int = 300,
        **overrides: Any,
    ) -> dict[str, Any]:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": TEST_ISSUER,
            "aud": TEST_AUDIENCE,
            "sub": subject,
            "iat": now,
            "exp": now + lifetime_seconds,
            "typ": "Bearer",
            "azp": "crm-web",
            "realm_access": {"roles": list(roles)},
        }
        claims.update(overrides)
        return claims

    def sign(self, claims: Mapping[str, Any], *, kid: str | None = None) -> str:
        return jwt.encode(
            dict(claims), self.private_key, algorithm="RS256", headers={"kid": kid or self.kid}
        )

    def mint(
        self, subject: str = "test-subject", roles: Iterable[str] = (), **overrides: Any
    ) -> str:
        return self.sign(self.claims(subject, roles, **overrides))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge_token(
    header: Mapping[str, Any], claims: Mapping[str, Any], signature: bytes = b""
) -> str:
    """Build a JWT by hand - used to create tokens an attacker could send (alg=none, etc.)."""
    head = _b64(json.dumps(header).encode())
    body = _b64(json.dumps(claims).encode())
    return f"{head}.{body}.{_b64(signature)}"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def tamper_payload(token: str, **changes: Any) -> str:
    """Change claims of a signed token but keep the original signature (must be rejected)."""
    head, body, signature = token.split(".")
    claims = json.loads(_unb64(body))
    claims.update(changes)
    return f"{head}.{_b64(json.dumps(claims).encode())}.{signature}"


def hs256_signed_with_public_key(factory: TokenFactory, claims: Mapping[str, Any]) -> str:
    """Classic 'algorithm confusion' attack: HMAC-sign with the (public!) RSA key as secret."""
    public_pem = factory.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = {"alg": "HS256", "typ": "JWT", "kid": factory.kid}
    signing_input = forge_token(header, claims).rsplit(".", 1)[0]
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"
