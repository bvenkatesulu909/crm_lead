"""FastAPI dependencies that protect endpoints.

    @router.get("/things")
    def list_things(principal: Principal = Depends(require_any_permission(Permission.X))): ...

- ``get_principal``: 401 unless a valid bearer token is sent; 403 if the identity is not
  allowed into the CRM.
- ``require_any_permission``: additionally 403 unless the principal has one of the permissions.
Record-level checks (which rows) are done afterwards by each module's policies.
"""

import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.auth.tokens import (
    AuthServiceUnavailableError,
    InvalidTokenError,
    TokenVerifier,
    VerifiedToken,
)
from app.core.db import get_db_session
from app.core.request_context import set_client_id
from app.modules.identity.service import forbidden, resolve_principal

logger = logging.getLogger(__name__)

# auto_error=False: we raise our own 401 in the standard Problem Details format.
bearer_scheme = HTTPBearer(auto_error=False, description="Keycloak access token")

_UNAUTHORIZED_DETAIL = "Missing or invalid access token."


def _unauthorized(error: str | None) -> HTTPException:
    # RFC 6750: tell the client which authentication scheme is expected.
    challenge = f'Bearer error="{error}"' if error else "Bearer"
    return HTTPException(
        status_code=401, detail=_UNAUTHORIZED_DETAIL, headers={"WWW-Authenticate": challenge}
    )


def get_verified_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> VerifiedToken:
    """Only checks the token itself - for people who signed up but have no CRM user yet."""
    if credentials is None:
        raise _unauthorized(None)
    verifier: TokenVerifier = request.app.state.token_verifier
    try:
        token = verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        # The reason goes to the log only; the token itself is never logged.
        logger.info("access token rejected", extra={"reason": str(exc)})
        raise _unauthorized("invalid_token") from exc
    except AuthServiceUnavailableError as exc:
        logger.warning("cannot reach identity provider to verify token")
        raise HTTPException(status_code=503, detail="Authentication service unavailable.") from exc
    # Only after verification: an unverified token could claim to be any application.
    set_client_id(token.claims.get("azp"))
    return token


def get_principal(
    token: VerifiedToken = Depends(get_verified_token),
    session: Session = Depends(get_db_session),
) -> Principal:
    return resolve_principal(session, token)


def require_any_permission(*permissions: Permission) -> Callable[..., Principal]:
    required = frozenset(permissions)

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.permissions & required:
            logger.info(
                "permission denied",
                extra={"subject": principal.subject, "required": sorted(required)},
            )
            raise forbidden()
        return principal

    return dependency
