import base64
import hashlib
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from crm_mcp.auth import Authenticator, AuthError, LoginFlow, TokenSet, pkce_pair, wait_for_callback
from crm_mcp.config import ConfigError, Settings, load_settings
from tests.conftest import SETTINGS, FakeServices, fake_login

# --- configuration ------------------------------------------------------------------------


def test_defaults_point_at_the_local_stack() -> None:
    settings = load_settings({})
    assert settings.api_url == "http://localhost:8000/api/v1"
    assert settings.redirect_uri == "http://127.0.0.1:8765/callback"


@pytest.mark.parametrize(
    "env",
    [
        {"CRM_MCP_API_URL": "http://crm.example.com/api/v1"},  # token over plain HTTP
        {"CRM_MCP_ISSUER": "http://192.168.1.10:8080/realms/crm"},
        {"CRM_MCP_API_URL": "ftp://localhost/api"},
        {"CRM_MCP_REDIRECT_PORT": "abc"},
    ],
)
def test_unsafe_or_invalid_settings_are_refused(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_settings(env)


def test_https_addresses_are_accepted() -> None:
    settings = load_settings({"CRM_MCP_API_URL": "https://api.example.com/api/v1/"})
    assert settings.api_url == "https://api.example.com/api/v1"


# --- PKCE login flow ----------------------------------------------------------------------


def test_pkce_challenge_is_the_s256_hash_of_the_verifier() -> None:
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()
    assert 43 <= len(verifier) <= 128


def test_authorization_url_asks_for_a_code_with_pkce_and_loopback_redirect() -> None:
    flow = LoginFlow(SETTINGS)
    url = urlsplit(flow.authorization_url())
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.path == "/realms/crm/protocol/openid-connect/auth"
    assert query == {
        "client_id": "crm-mcp",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": "http://127.0.0.1:8765/callback",
        "state": flow.state,
        "code_challenge": flow.challenge,
        "code_challenge_method": "S256",
    }


@pytest.mark.parametrize(
    "callback, message",
    [
        ({"error": "access_denied"}, "not completed"),
        ({"code": "c", "state": "someone-else"}, "did not match"),
        ({"state": "<state>"}, "no code"),
    ],
)
def test_bad_callbacks_are_refused_before_any_token_request(
    callback: dict[str, str], message: str, http: httpx.Client, services: FakeServices
) -> None:
    flow = LoginFlow(SETTINGS)
    callback = {k: flow.state if v == "<state>" else v for k, v in callback.items()}
    with pytest.raises(AuthError, match=message):
        flow.exchange(callback, http)
    assert services.requests == []


def test_code_is_exchanged_with_the_verifier(http: httpx.Client, services: FakeServices) -> None:
    flow = LoginFlow(SETTINGS)
    tokens = flow.exchange({"code": "abc", "state": flow.state}, http)
    form = parse_qs(services.requests[0].content.decode())
    assert form["code_verifier"] == [flow.verifier]
    assert form["client_id"] == ["crm-mcp"] and "client_secret" not in form
    assert tokens.access_token == "access-1"


def test_tokens_never_appear_in_repr() -> None:
    tokens = TokenSet(access_token="secret-access", refresh_token="secret-refresh", expires_at=1)
    assert "secret" not in repr(tokens)


# --- Authenticator --------------------------------------------------------------------------


def make_auth(http: httpx.Client, clock: list[float]) -> tuple[Authenticator, dict[str, str]]:
    opened: dict[str, str] = {}
    auth = Authenticator(
        SETTINGS,
        http,
        open_browser=lambda url: opened.update(url=url),
        wait=fake_login(opened),
        clock=lambda: clock[0],
    )
    return auth, opened


def test_signs_in_once_then_reuses_the_token(http: httpx.Client, services: FakeServices) -> None:
    clock = [1000.0]
    auth, opened = make_auth(http, clock)
    assert auth.access_token() == "access-1"
    assert auth.access_token() == "access-1"
    assert services.issued == 1 and auth.sign_ins == 1
    assert "/protocol/openid-connect/auth?" in opened["url"]


def test_expired_token_is_refreshed_without_a_new_sign_in(
    http: httpx.Client, services: FakeServices
) -> None:
    clock = [1000.0]
    auth, _ = make_auth(http, clock)
    auth.access_token()
    clock[0] += 290  # within 30 s of the 300 s lifetime
    assert auth.access_token() == "access-2"
    form = parse_qs(services.requests[-1].content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["refresh-1"]
    assert auth.sign_ins == 1


def test_refused_refresh_falls_back_to_signing_in(
    http: httpx.Client, services: FakeServices
) -> None:
    clock = [1000.0]
    auth, _ = make_auth(http, clock)
    auth.access_token()
    auth._tokens.refresh_token = "revoked"  # type: ignore[union-attr]
    auth.invalidate()
    assert auth.access_token() == "access-2"
    assert auth.sign_ins == 2


# --- the real loopback callback server ------------------------------------------------------


def test_callback_server_returns_the_query_and_only_answers_on_callback() -> None:
    port = 18765
    result: dict[str, str] = {}
    ready = threading.Event()

    def run() -> None:
        result.update(wait_for_callback(port, 10, ready.set))

    thread = threading.Thread(target=run)
    thread.start()
    assert ready.wait(5)
    assert httpx.get(f"http://127.0.0.1:{port}/other").status_code == 404
    page = httpx.get(f"http://127.0.0.1:{port}/callback?code=xyz&state=s1")
    thread.join(5)
    assert page.status_code == 200 and "Signed in" in page.text
    assert result == {"code": "xyz", "state": "s1"}


def test_callback_server_times_out() -> None:
    with pytest.raises(AuthError, match="timed out"):
        wait_for_callback(18766, 0.2, lambda: None)


def test_settings_model_is_immutable() -> None:
    with pytest.raises(AttributeError):
        Settings().api_url = "x"  # type: ignore[misc]
