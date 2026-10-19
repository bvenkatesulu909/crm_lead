"""Access-token verification (OAuth 2.0 bearer tokens issued by Keycloak).

A token is accepted only if ALL of these hold:

- it is a well-formed JWT signed with RS256 (no "none", no HMAC: this blocks
  algorithm-confusion attacks);
- the signature verifies with one of the issuer's published public keys (JWKS);
- ``iss`` equals the configured issuer exactly;
- ``aud`` contains the configured audience (``crm-api``);
- ``exp`` is in the future, ``nbf``/``iat`` are not in the future (small clock-skew allowance);
- ``sub`` is present and ``typ`` is ``Bearer`` (an ID token is not an access token).

Every failure raises ``InvalidTokenError``. Its message is for server logs only; clients always
get the same generic 401 so they cannot learn which check failed.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

ALLOWED_ALGORITHMS = ["RS256"]
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]


class InvalidTokenError(Exception):
    """The token must be rejected. The message explains why, for server logs only."""


class AuthServiceUnavailableError(Exception):
    """The issuer's signing keys could not be fetched (e.g. Keycloak is down)."""


class SigningKeyProvider(Protocol):
    def get_signing_key(self, token: str) -> Any: ...


class JwksKeyProvider:
    """Fetches the issuer's public keys over HTTP and caches them (refetches on unknown key IDs)."""

    def __init__(self, jwks_url: str) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)

    def get_signing_key(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except PyJWKClientConnectionError as exc:
            raise AuthServiceUnavailableError("cannot fetch JWKS") from exc
        except (PyJWKClientError, jwt.PyJWTError) as exc:
            raise InvalidTokenError(f"no matching signing key: {type(exc).__name__}") from exc


class StaticKeyProvider:
    """Uses a fixed JWKS document. Tests use this with their own key pair; the verification
    rules in TokenVerifier are exactly the same as in production."""

    def __init__(self, jwks: Mapping[str, Any]) -> None:
        self._keys = {key["kid"]: PyJWK(key).key for key in jwks["keys"]}

    def get_signing_key(self, token: str) -> Any:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token header") from exc
        if kid not in self._keys:
            raise InvalidTokenError("unknown key id")
        return self._keys[kid]


@dataclass(frozen=True)
class VerifiedToken:
    subject: str
    issuer: str
    roles: frozenset[str]
    claims: Mapping[str, Any]


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_provider: SigningKeyProvider,
        clock_skew_seconds: int = 30,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = key_provider
        self._leeway = clock_skew_seconds

    def verify(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise InvalidTokenError("algorithm not allowed")

        key = self._keys.get_signing_key(token)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(f"rejected: {type(exc).__name__}") from exc

        if claims.get("typ") != "Bearer":
            raise InvalidTokenError("not an access token")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise InvalidTokenError("missing subject")

        realm_access = claims.get("realm_access")
        raw_roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        roles = frozenset(role for role in raw_roles if isinstance(role, str))
        return VerifiedToken(subject=subject, issuer=self._issuer, roles=roles, claims=claims)
