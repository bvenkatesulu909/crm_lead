"""Consistent error responses in the "Problem Details" format (RFC 9457).

Every error the API returns has the same shape, so the frontend needs one error handler:

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "...", "request_id": "..."}
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

PROBLEM_JSON = "application/problem+json"


def _phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


class DomainError(Exception):
    """A business-rule failure the client can act on (e.g. an invalid status change).

    ``code`` is a stable, machine-readable identifier the frontend can switch on;
    ``detail`` is a human-readable explanation. Both are safe to show to the caller.
    """

    status_code = 400
    code = "domain_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ProblemDetails(BaseModel):
    """Body of every error response (documents the format in OpenAPI)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    request_id: str | None = None
    code: str | None = Field(
        default=None, description="Stable machine-readable error code, e.g. 'version_conflict'."
    )
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="Field-level problems (validation errors only)."
    )


def problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` entries for the given error status codes."""
    descriptions = {
        401: "Missing or invalid access token.",
        403: "Authenticated, but not allowed to do this.",
        404: "Not found - or not visible to you (the API does not distinguish).",
        409: "Conflicts with the current state (invalid status change, stale version, ...).",
        422: "The request data is invalid.",
    }
    return {
        code: {"model": ProblemDetails, "description": descriptions.get(code, "Error")}
        for code in status_codes
    }


def problem_response(
    status_code: int,
    *,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
    code: str | None = None,
) -> JSONResponse:
    title = _phrase(status_code)
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail or title,
        "request_id": get_request_id(),
    }
    if code:
        body["code"] = code
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_JSON, headers=headers)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # narrows the type for mypy
        raise exc
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(exc.status_code, detail=detail, headers=exc.headers)


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    # Deliberately leave out the rejected "input" value: it may contain personal data
    # or secrets, and the client already knows what it sent.
    errors = [
        {"location": list(err["loc"]), "message": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return problem_response(422, detail="The request contains invalid data.", errors=errors)


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):
        raise exc
    return problem_response(exc.status_code, detail=exc.detail, code=exc.code)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    # Unexpected exceptions (500) are handled in RequestContextMiddleware so the response
    # still carries the request ID.
