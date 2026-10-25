"""Sign-in as the real user: OAuth 2.0 Authorization Code + PKCE with a loopback redirect.

The user types their password on Keycloak's own login page in their browser; this program only
receives a one-time code on http://127.0.0.1:<port>/callback and exchanges it (with the PKCE
verifier) for tokens. Tokens are kept in memory only (ADR 0015): after a restart the user signs
in again. They are never logged or shown.
"""

import base64
import hashlib
import logging
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from crm_mcp.config import Settings

log = logging.getLogger(__name__)

# Refresh a little before expiry so a token never runs out in the middle of a call.
EXPIRY_MARGIN_SECONDS = 30


class AuthError(Exception):
    """Sign-in failed. The message is safe to show (it never contains a token or code)."""


@dataclass
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    expires_at: float

    @classmethod
    def from_response(cls, data: dict[str, Any], now: float) -> "TokenSet":
        if data.get("token_type", "").lower() != "bearer" or "access_token" not in data:
            raise AuthError("Keycloak returned an unexpected token response")
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=now + float(data.get("expires_in", 60)),
        )

    def fresh(self, now: float) -> bool:
        return now < self.expires_at - EXPIRY_MARGIN_SECONDS


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) as defined in RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class LoginFlow:
    """One sign-in attempt: its own state and PKCE verifier, used once."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.verifier, self.challenge = pkce_pair()
        self.state = secrets.token_urlsafe(24)

    def authorization_url(self) -> str:
        query = {
            "client_id": self._settings.client_id,
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": self._settings.redirect_uri,
            "state": self.state,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._settings.issuer}/protocol/openid-connect/auth?{urlencode(query)}"

    def exchange(
        self, callback: dict[str, str], http: httpx.Client, now: float | None = None
    ) -> TokenSet:
        """Check the browser's callback and swap its one-time code for tokens."""
        if "error" in callback:
            raise AuthError(f"sign-in was not completed ({callback['error']})")
        # A different state means the callback was not started by this program (CSRF).
        if not secrets.compare_digest(callback.get("state", ""), self.state):
            raise AuthError("sign-in answer did not match this request; please try again")
        code = callback.get("code")
        if not code:
            raise AuthError("sign-in answer had no code")
        response = http.post(
            f"{self._settings.issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._settings.redirect_uri,
                "client_id": self._settings.client_id,
                "code_verifier": self.verifier,
            },
        )
        if response.status_code != 200:
            raise AuthError(f"Keycloak refused the sign-in (HTTP {response.status_code})")
        return TokenSet.from_response(response.json(), time.time() if now is None else now)


_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>crm-lead</title>"
    "<body style='font-family:sans-serif;margin:3rem'><h1>{title}</h1><p>{text}</p></body>"
)


def wait_for_callback(
    port: int, timeout_seconds: float, on_ready: Callable[[], object]
) -> dict[str, str]:
    """Serve http://127.0.0.1:<port>/callback until the browser arrives (or time runs out).

    ``on_ready`` opens the browser once the port is listening: with an existing Keycloak session
    the browser comes back immediately, before a later-started server could catch it.
    """
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
            parts = urlsplit(self.path)
            if parts.path != "/callback":
                self.send_error(404)
                return
            result.update({k: v[0] for k, v in parse_qs(parts.query).items()})
            ok = "code" in result
            body = _PAGE.format(
                title="Signed in" if ok else "Sign-in not completed",
                text="You can close this window and return to Claude."
                if ok
                else "Close this window and try again from Claude.",
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:
            pass  # the request line contains the one-time code: never log it

    # Bound to 127.0.0.1 only: other devices on the network cannot reach the callback.
    try:
        server = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise AuthError(f"port {port} for the sign-in answer is in use") from error
    with server:
        on_ready()
        deadline = time.monotonic() + timeout_seconds
        while not result:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuthError("sign-in timed out; ask Claude to try again")
            server.timeout = min(remaining, 1.0)
            server.handle_request()
    return result


class Authenticator:
    """Hands out a valid access token, signing in or refreshing when needed."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.Client,
        *,
        open_browser: Callable[[str], object] = webbrowser.open,
        wait: Callable[[int, float, Callable[[], object]], dict[str, str]] = wait_for_callback,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._http = http
        self._open_browser = open_browser
        self._wait = wait
        self._clock = clock
        self._tokens: TokenSet | None = None
        self._lock = threading.Lock()
        # Increases with every fresh sign-in, so callers can drop data cached for another user.
        self.sign_ins = 0

    def access_token(self) -> str:
        with self._lock:
            now = self._clock()
            if self._tokens and self._tokens.fresh(now):
                return self._tokens.access_token
            if self._tokens and self._tokens.refresh_token and self._refresh(now):
                return self._tokens.access_token
            self._login()
            assert self._tokens is not None  # noqa: S101 - set by _login or it raised
            return self._tokens.access_token

    def invalidate(self) -> None:
        """The API rejected the token: refresh (or sign in) on the next call."""
        with self._lock:
            if self._tokens:
                self._tokens.expires_at = 0

    def _refresh(self, now: float) -> bool:
        assert self._tokens is not None and self._tokens.refresh_token  # noqa: S101
        response = self._http.post(
            f"{self._settings.issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._tokens.refresh_token,
                "client_id": self._settings.client_id,
            },
        )
        if response.status_code != 200:
            log.info("token refresh refused (HTTP %s); signing in again", response.status_code)
            self._tokens = None
            return False
        self._tokens = TokenSet.from_response(response.json(), now)
        return True

    def _login(self) -> None:
        flow = LoginFlow(self._settings)
        url = flow.authorization_url()
        # stdout is the MCP channel, so the address goes to the log (stderr).
        log.warning("Opening the crm-lead sign-in page. If no browser opens, visit: %s", url)
        callback = self._wait(
            self._settings.redirect_port,
            self._settings.login_timeout_seconds,
            lambda: self._open_browser(url),
        )
        self._tokens = flow.exchange(callback, self._http, self._clock())
        self.sign_ins += 1
