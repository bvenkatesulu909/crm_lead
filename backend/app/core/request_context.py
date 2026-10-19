"""Per-request context: a request ID for tracing, an access log line, and a safe 500 fallback.

Written as a plain ASGI middleware (not BaseHTTPMiddleware) so the request ID stays available
to log calls everywhere in the request, including in exception handlers.
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# Accept a caller's request ID only if it is short and harmless, so it cannot be used to
# inject fake lines or huge values into the logs.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

logger = logging.getLogger("app.request")


def get_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex
        token = _request_id.set(request_id)

        status_code = 500
        response_started = False
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Full details go to the server log only; the client gets a generic message.
            logger.exception("unhandled error")
            if not response_started:
                # Imported here to avoid a circular import (errors uses get_request_id).
                from app.core.errors import problem_response

                response = problem_response(500, detail="An unexpected error occurred.")
                await response(scope, receive, send_with_request_id)
        finally:
            # Path only, never the query string: it can contain personal data.
            logger.info(
                "request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            _request_id.reset(token)
