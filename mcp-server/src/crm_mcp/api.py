"""The only way this program reaches CRM data: GET requests to the CRM API as the signed-in user.

All tenant, role and record-level checks happen in the API (ADR 0015 (originally 0010), decision 1). This client
only turns HTTP answers into short, safe messages - it never echoes tokens or raw bodies.
"""

import logging
from typing import Any

import httpx

from crm_mcp.auth import Authenticator
from crm_mcp.config import Settings

log = logging.getLogger(__name__)


class ApiError(Exception):
    """A CRM API call failed. The message is safe to show to Claude and the user."""


class CrmApi:
    def __init__(self, settings: Settings, auth: Authenticator, http: httpx.Client) -> None:
        self._base = settings.api_url
        self._auth = auth
        self._http = http

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        response = self._send(path, clean)
        if response.status_code == 401:
            # Expired or revoked session: refresh (or sign in again) once, then retry.
            self._auth.invalidate()
            response = self._send(path, clean)
        return self._result(response)

    def _send(self, path: str, params: dict[str, Any]) -> httpx.Response:
        token = self._auth.access_token()
        try:
            return self._http.get(
                f"{self._base}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            raise ApiError(f"the CRM API is not reachable at {self._base}") from error

    @staticmethod
    def _result(response: httpx.Response) -> Any:
        status = response.status_code
        if status == 200:
            return response.json()
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
