"""The only way this program reaches CRM data: requests to the CRM API as the signed-in user.

Reading is GET. The one write is ``post_proposal``: a POST to the single endpoint that only
creates a pending proposal for a person to approve (ADR 0020). No other path can be posted to.
All tenant, role and record-level checks happen in the API (ADR 0015, decision 1). This client
only turns HTTP answers into short, safe messages - it never echoes tokens or raw bodies.
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from crm_mcp.auth import Authenticator
from crm_mcp.config import Settings

log = logging.getLogger(__name__)


class ApiError(Exception):
    """A CRM API call failed. The message is safe to show to Claude and the user."""


PROPOSAL_PATH = "/approvals/proposals/external"

# What a refused proposal means, by the API's stable error code. Fixed sentences only: the
# API's own text can quote what a person typed.
PROPOSAL_REFUSALS: dict[str, str] = {
    "external_client_not_allowed": "this application may not send proposals to the CRM",
    "agent_unavailable": (
        "AI clients are switched off for your organisation; ask a CRM administrator to turn on "
        "'AI clients (MCP)' on the AI agents page"
    ),
    "mcp_proposal_limit_reached": "you have reached the hourly limit for proposals; try later",
    "agent_action_limit_reached": "too many of your proposals are already waiting for a decision",
    "proposal_blocked": "the CRM's safety check refused this proposal (links, instructions or "
    "a duplicate are not allowed); nothing was created",
}


class CrmApi:
    def __init__(
        self,
        settings: Settings,
        auth: Authenticator,
        http: httpx.Client,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base = settings.api_url
        self._auth = auth
        self._http = http
        self._clock = clock
        self._max_per_minute = settings.max_calls_per_minute
        self._recent: deque[float] = deque()

    def _throttle(self) -> None:
        """At most ``max_calls_per_minute`` calls in any 60 seconds; the rest are refused here,
        so a looping agent never reaches the CRM."""
        now = self._clock()
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self._max_per_minute:
            raise ApiError("too many calls in the last minute; wait a minute and try again")
        self._recent.append(now)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        response = self._send(path, clean)
        if response.status_code == 401:
            # Expired or revoked session: refresh (or sign in again) once, then retry.
            self._auth.invalidate()
            response = self._send(path, clean)
        return self._result(response)

    def post_proposal(self, body: dict[str, Any]) -> Any:
        """Send one proposal. The only POST this program can make, and only to PROPOSAL_PATH."""
        response = self._send(PROPOSAL_PATH, method="POST", body=body)
        if response.status_code == 401:
            self._auth.invalidate()  # nothing was processed on a 401, so one retry is safe
            response = self._send(PROPOSAL_PATH, method="POST", body=body)
        return self._result(response, refusals=PROPOSAL_REFUSALS)

    def _send(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self._throttle()
        token = self._auth.access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            if method == "POST":
                return self._http.post(f"{self._base}{path}", json=body, headers=headers)
            return self._http.get(f"{self._base}{path}", params=params, headers=headers)
        except httpx.HTTPError as error:
            raise ApiError(f"the CRM API is not reachable at {self._base}") from error

    @staticmethod
    def _result(response: httpx.Response, refusals: dict[str, str] | None = None) -> Any:
        status = response.status_code
        code = _problem_code(response) if refusals and status >= 400 else None
        if code is not None and refusals and code in refusals:
            raise ApiError(refusals[code])
        if status in (200, 201):
            try:
                return response.json()
            except ValueError:
                raise ApiError("the CRM API answered in an unexpected format") from None
        if status == 404:
            # The API answers 404 both for "does not exist" and "not yours" (no information leak).
            raise ApiError("not found, or you are not allowed to see it")
        if status == 403:
            code = _problem_code(response)
            if code == "access_pending":
                raise ApiError("your CRM account is waiting for approval")
            raise ApiError("your role is not allowed to do this")
        if status == 401:
            raise ApiError("the CRM did not accept your sign-in")
        if status == 429:
            raise ApiError("the CRM is busy right now; wait a moment and try again")
        if status == 422:
            raise ApiError("the CRM rejected the input (check IDs, dates and filter values)")
        log.info("CRM API answered HTTP %s", status)
        raise ApiError(f"the CRM API failed (HTTP {status}); try again later")


def _problem_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None
