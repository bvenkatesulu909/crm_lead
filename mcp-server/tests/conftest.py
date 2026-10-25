"""A fake Keycloak + CRM API behind httpx.MockTransport, so unit tests need no running services."""

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from crm_mcp.api import CrmApi
from crm_mcp.auth import Authenticator
from crm_mcp.config import Settings
from crm_mcp.tools import CrmTools

SETTINGS = Settings()
TOKEN_URL = f"{SETTINGS.issuer}/protocol/openid-connect/token"
ME_STAFF = {
    "user_id": "a1000000-0000-4000-8000-0000000000aa",
    "display_name": "Alex Agent",
    "email": "agent1@alpha.example.test",
    "tenant_name": "Alpha Demo",
    "user_type": "staff",
    "roles": ["sales_agent"],
}

Handler = Callable[[httpx.Request], httpx.Response]


class FakeServices:
    """Records every request; API routes answer with `routes[path]` (a response or a handler)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Any] = {"/me": ME_STAFF}
        self.issued = 0
        self.valid_tokens: set[str] = set()

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["revoked"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.issued += 1
        token = f"access-{self.issued}"
        self.valid_tokens.add(token)
        return httpx.Response(
            200,
            json={
                "token_type": "Bearer",
                "access_token": token,
                "refresh_token": f"refresh-{self.issued}",
                "expires_in": 300,
            },
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url).startswith(TOKEN_URL):
            return self._token(request)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_tokens:
            return httpx.Response(401, json={"title": "Unauthorized"})
        path = urlsplit(str(request.url)).path.removeprefix("/api/v1")
        route = self.routes.get(path)
        if route is None:
            return httpx.Response(404, json={"title": "Not found"})
        if callable(route):
            result: httpx.Response = route(request)
            return result
        return httpx.Response(200, json=route)

    def api_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if "/api/v1" in str(r.url)]


def fake_login(auth_holder: dict[str, str]) -> Callable[..., dict[str, str]]:
    """Stands in for the browser: 'signs in' and returns the code with the request's state."""

    def wait(port: int, timeout: float, on_ready: Callable[[], object]) -> dict[str, str]:
        on_ready()
        state = parse_qs(urlsplit(auth_holder["url"]).query)["state"][0]
        return {"code": "one-time-code", "state": state}

    return wait


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def http(services: FakeServices) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(services.handle))


@pytest.fixture
def opened() -> dict[str, str]:
    return {}


@pytest.fixture
def auth(http: httpx.Client, opened: dict[str, str]) -> Authenticator:
    return Authenticator(
        SETTINGS, http, open_browser=lambda url: opened.update(url=url), wait=fake_login(opened)
    )


@pytest.fixture
def api(http: httpx.Client, auth: Authenticator) -> CrmApi:
    return CrmApi(SETTINGS, auth, http)


@pytest.fixture
def crm(api: CrmApi, auth: Authenticator) -> CrmTools:
    return CrmTools(api, auth)
