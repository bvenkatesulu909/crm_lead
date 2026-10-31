"""End-to-end checks against the REAL local Keycloak + CRM API (marker `live`).

Signs in through Keycloak's login page with the fictional test users from realm-crm.json, using
the crm-mcp client exactly as the MCP server does (PKCE, loopback redirect), then calls the tools.

Skipped unless Keycloak (localhost:9080) and the API (localhost:8000) are running and the test
password is available: CRM_TEST_KEYCLOAK_USER_PASSWORD in the environment or in the file named
by CRM_MCP_TEST_ENV_FILE (default: ../backend/.env).
"""

import html
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from crm_mcp.api import ApiError, CrmApi
from crm_mcp.auth import Authenticator
from crm_mcp.config import load_settings
from crm_mcp.tools import CrmTools

pytestmark = pytest.mark.live
SETTINGS = load_settings()  # honours CRM_MCP_API_URL, to point the tests at another API
OIDC = f"{SETTINGS.issuer}/protocol/openid-connect"


def _password() -> str | None:
    if value := os.environ.get("CRM_TEST_KEYCLOAK_USER_PASSWORD"):
        return value
    default = Path(__file__).resolve().parents[2] / "backend" / ".env"
    env_file = Path(os.environ.get("CRM_MCP_TEST_ENV_FILE", default))
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "CRM_TEST_KEYCLOAK_USER_PASSWORD" and value.strip():
                return value.strip().strip('"')
    return None


class Secret(str):
    """A str whose repr is hidden, so pytest never prints the password in a failure report."""

    def __repr__(self) -> str:
        return "Secret('***')"


@pytest.fixture(scope="module")
def password() -> str:
    value = _password()
    if not value:
        pytest.skip("CRM_TEST_KEYCLOAK_USER_PASSWORD not configured")
    try:
        httpx.get(f"{SETTINGS.issuer}/.well-known/openid-configuration", timeout=3)
        httpx.get(f"{SETTINGS.api_url}/health", timeout=3)
    except httpx.HTTPError:
        pytest.skip("Keycloak or the CRM API is not running")
    return Secret(value)


def fill_login_form(url: str, username: str, password: str) -> dict[str, str]:
    """Plays the user's browser: opens the sign-in page, submits the form, returns the callback."""
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        page = browser.get(url)
        if page.status_code == 302:  # Keycloak refused before showing the form
            return _query(page.headers["location"])
        match = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
        assert match, "Keycloak login form not found"
        # Keycloak's cookies are "Secure"; browsers still send them to localhost, httpx does not.
        cookies = "; ".join(f"{k}={v}" for k, v in browser.cookies.items())
        result = browser.post(
            html.unescape(match.group(1)),
            data={"username": username, "password": password},
            headers={"Cookie": cookies},
        )
    assert result.status_code == 302, "login was not accepted"
    location = result.headers["location"]
    assert location.startswith(SETTINGS.redirect_uri)
    return _query(location)


def _query(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def tools_for(username: str, password: str) -> CrmTools:
    http = httpx.Client(timeout=20)
    opened: dict[str, str] = {}

    def wait(port: int, timeout: float, on_ready: Callable[[], object]) -> dict[str, str]:
        on_ready()  # "opens the browser": records the sign-in address
        return fill_login_form(opened["url"], username, password)

    auth = Authenticator(SETTINGS, http, open_browser=lambda url: opened.update(url=url), wait=wait)
    return CrmTools(CrmApi(SETTINGS, auth, http), auth)


# --- Keycloak client configuration ----------------------------------------------------------


def test_password_grant_is_refused_for_the_mcp_client(password: str) -> None:
    response = httpx.post(
        f"{OIDC}/token",
        data={
            "grant_type": "password",
            "client_id": "crm-mcp",
            "username": "alpha.agent1",
            "password": password,
        },
    )
    assert response.status_code in (400, 401)


def test_login_without_pkce_is_refused(password: str) -> None:
    query = {
        "client_id": "crm-mcp",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": SETTINGS.redirect_uri,
        "state": "s",
    }
    response = httpx.get(f"{OIDC}/auth", params=query, follow_redirects=False)
    # Keycloak sends the browser back with an error instead of showing the login page.
    assert response.status_code == 302
    assert "error=invalid_request" in response.headers["location"]


def test_foreign_redirect_uri_is_refused(password: str) -> None:
    query = {
        "client_id": "crm-mcp",
        "response_type": "code",
        "redirect_uri": "http://evil.example.com/callback",
        "code_challenge": "x" * 43,
        "code_challenge_method": "S256",
    }
    response = httpx.get(f"{OIDC}/auth", params=query, follow_redirects=False)
    assert response.status_code == 400  # Keycloak shows an error page, never redirects there


# --- tools as real users --------------------------------------------------------------------


def test_sales_agent_signs_in_and_sees_only_own_leads(password: str) -> None:
    crm = tools_for("alpha.agent1", password)
    me = crm.whoami()["data"]
    assert me["organisation"].startswith("Alpha Demo") and me["roles"] == ["sales_agent"]
    leads = crm.search_leads(limit=50)["data"]
    my_id = crm.me()["user_id"]
    assert all(lead["owner_id"] == my_id for lead in leads)


def test_other_tenant_and_other_agent_get_not_found(password: str) -> None:
    manager = tools_for("alpha.manager", password)
    agent1_id = tools_for("alpha.agent1", password).me()["user_id"]
    leads = manager.search_leads(limit=50)["data"]
    agent1_leads = [lead for lead in leads if lead["owner_id"] == agent1_id]
    if not agent1_leads:
        pytest.skip("no lead owned by alpha.agent1 in the seed data")
    lead_id = agent1_leads[0]["id"]
    assert manager.get_lead(lead_id)["data"]["id"] == lead_id  # the manager may see it

    with pytest.raises(ApiError, match="not allowed to see it"):
        tools_for("alpha.agent2", password).get_lead(lead_id)  # same tenant, not the owner
    with pytest.raises(ApiError, match="not allowed to see it"):
        tools_for("beta.admin", password).get_lead(lead_id)  # other tenant


def test_portal_customer_cannot_use_the_mcp_server(password: str) -> None:
    with pytest.raises(ApiError):
        tools_for("alpha.customer1", password).whoami()


def test_dashboard_and_tasks_answer_for_a_manager(password: str) -> None:
    crm = tools_for("alpha.manager", password)
    assert crm.get_dashboard()["record_type"] == "dashboard"
    assert "total" in crm.list_my_tasks("next_7_days")
    deals = crm.list_opportunities(only_mine=False)["data"]
    assert all(
        d["stage"] in {"prospecting", "qualification", "proposal", "negotiation"} for d in deals
    )


# --- proposals through the real Keycloak + API (ADR 0020) -------------------------------------
# These change only the "AI clients (MCP)" switch (put back afterwards) and leave rejected
# proposals behind; no lead, task or owner is ever changed because nobody approves.


def _http_as(crm: CrmTools) -> Callable[..., httpx.Response]:
    """Calls the API with the same signed-in token the tools use (for the admin/approver steps)."""

    def call(method: str, path: str, **kwargs: object) -> httpx.Response:
        token = crm._auth.access_token()  # noqa: SLF001 - a test acting as that signed-in person
        return httpx.request(
            method,
            f"{SETTINGS.api_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
            **kwargs,  # type: ignore[arg-type]
        )

    return call


@pytest.fixture(scope="module")
def propose_ready(password: str) -> None:
    openapi = httpx.get(f"{SETTINGS.api_url.removesuffix('/api/v1')}/openapi.json", timeout=10)
    if "/api/v1/approvals/proposals/external" not in openapi.text:
        pytest.skip("the running API does not have the proposal endpoint (start the new code)")


def _set_switch(admin: Callable[..., httpx.Response], enabled: bool) -> None:
    current = admin("GET", "/agents/mcp_client").json()
    body: dict[str, object] = {"enabled": enabled}
    if current.get("version"):
        body["version"] = current["version"]
    response = admin("PATCH", "/agents/mcp_client", json=body)
    assert response.status_code == 200, response.text


def test_a_real_proposal_waits_for_a_different_person(password: str, propose_ready: None) -> None:
    admin = _http_as(tools_for("alpha.admin", password))
    manager_tools = tools_for("alpha.manager", password)
    manager = _http_as(manager_tools)
    agent = tools_for("alpha.agent1", password)
    agent_http = _http_as(agent)
    leads = agent.search_leads(limit=50)["data"]
    if not leads:
        pytest.skip("alpha.agent1 owns no lead in the seed data")
    lead = leads[0]
    _set_switch(admin, False)  # a known starting point, whatever an earlier run left behind
    try:
        with pytest.raises(ApiError, match="switched off"):
            agent.propose_lead_status(lead["id"], "contacted", "Live test: switch is off")

        _set_switch(admin, True)
        result = agent.propose_lead_status(lead["id"], "contacted", "Live test: spoke to them")
        assert result["record_type"] == "proposal" and "Nothing has changed" in str(result["data"])
        proposal_id = result["data"]["proposal_id"]

        # Nothing changed, and the proposal is stored as coming from the MCP client.
        assert agent.get_lead(lead["id"])["data"]["status"] == lead["status"]
        stored = agent_http("GET", f"/approvals/actions/{proposal_id}").json()
        assert stored["status"] == "pending"
        assert stored["agent"] == "mcp_client" and stored["via_client"] == "crm-mcp"

        # The person who asked cannot decide; a manager can reject; the lead is still unchanged.
        own = agent_http(
            "POST", f"/approvals/actions/{proposal_id}/approve", json={"version": stored["version"]}
        )
        assert own.status_code in (403, 404)
        rejected = manager(
            "POST",
            f"/approvals/actions/{proposal_id}/reject",
            json={"version": stored["version"], "note": "Live test: rejecting on purpose"},
        )
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
        assert agent.get_lead(lead["id"])["data"]["status"] == lead["status"]
    finally:
        _set_switch(admin, False)


def test_a_proposal_on_a_lead_of_another_agent_is_not_found(
    password: str, propose_ready: None
) -> None:
    admin = _http_as(tools_for("alpha.admin", password))
    manager = tools_for("alpha.manager", password)
    agent1_id = tools_for("alpha.agent1", password).me()["user_id"]
    owned = [
        lead for lead in manager.search_leads(limit=50)["data"] if lead["owner_id"] == agent1_id
    ]
    if not owned:
        pytest.skip("no lead owned by alpha.agent1 in the seed data")
    _set_switch(admin, True)
    try:
        with pytest.raises(ApiError, match="not allowed to see it"):
            tools_for("alpha.agent2", password).propose_lead_status(
                owned[0]["id"], "contacted", "Live test: not my lead"
            )
    finally:
        _set_switch(admin, False)


def test_portal_customers_cannot_propose(password: str, propose_ready: None) -> None:
    with pytest.raises(ApiError):
        tools_for("alpha.customer1", password).propose_lead_status(
            "11111111-1111-4111-8111-111111111111", "contacted", "x"
        )
