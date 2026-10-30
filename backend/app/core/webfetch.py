"""The hardened page fetcher (ADR 0019): the only code that fetches a web page for a user.

It refuses by default. A page may be fetched only from the host a source names (the model and the
user never give an address); only over https on port 443; only when EVERY address the name
resolves to is public, and the connection is then made to that address (a second DNS answer
cannot swap the machine after the check); only when robots.txt allows it; with a time limit, a
size limit, no cookies or credentials, and no compressed bodies. Redirects are followed only
inside the same host and every hop is checked again.

Nothing here touches the network on import. The resolver and the transport are parameters, so the
rules are tested without the internet (tests/test_webfetch.py); the real transport is tested
against a local TLS server (tests/test_webfetch_transport.py).
"""

import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

USER_AGENT = "crm-lead-webcheck/1.0"
ROBOTS_TOKEN = "crm-lead-webcheck"  # noqa: S105 - a crawler name, not a secret
MAX_URL_LENGTH = 2048
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# What a refusal says. The text never repeats what a server said or an address we resolved.
MESSAGES = {
    "bad_scheme": "Only https addresses are allowed.",
    "bad_url": "The address is not valid.",
    "bad_port": "Only the standard https port is allowed.",
    "userinfo": "Addresses with a user name or password are not allowed.",
    "bad_host": "The address is not on the source's host.",
    "ip_literal": "Addresses given as numbers are not allowed.",
    "no_address": "The host name could not be resolved.",
    "private_address": "The host resolves to an address that is not public.",
    "robots_disallowed": "The site's robots.txt does not allow this page.",
    "robots_unavailable": "The site's robots.txt could not be read.",
    "bad_redirect": "The redirect is not valid.",
    "too_many_redirects": "There were too many redirects.",
    "too_large": "The page is larger than the limit.",
    "bad_content_type": "The page is not a text type that is allowed.",
    "bad_encoding": "The page is encoded, which is not allowed.",
    "timeout": "The site did not answer in time.",
    "network_error": "The site could not be reached.",
    "rate_limited": "Too many requests to this site; try later.",
}


class FetchRefused(Exception):
    """A fetch that was not made or not accepted. ``code`` is stable; the message is fixed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(MESSAGES.get(code, "The fetch was refused."))


@dataclass(frozen=True)
class FetchPolicy:
    timeout_s: float = 10.0
    max_bytes: int = 1_000_000
    max_redirects: int = 2
    content_types: tuple[str, ...] = ("text/html", "application/json", "text/plain")
    user_agent: str = USER_AGENT


@dataclass(frozen=True)
class PinnedRequest:
    """One request to a ready-checked address. ``host`` is the name the certificate must match."""

    ip: str
    host: str
    target: str
    headers: dict[str, str]
    timeout: float
    max_bytes: int
    port: int = 443


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: dict[str, str]  # names in lower case
    body: bytes
    truncated: bool  # the body was longer than max_bytes and has been cut


@dataclass(frozen=True)
class FetchResult:
    status: int
    final_url: str
    content_type: str
    body: bytes
    address: str


Resolver = Callable[[str], list[str]]
Transport = Callable[[PinnedRequest], TransportResponse]


# --- which addresses and URLs ------------------------------------------------------------------

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


def is_public_address(address: str) -> bool:
    """True only for an address on the public internet. Everything else - loopback, private,
    link-local (including the cloud metadata address), carrier-grade NAT, multicast, reserved,
    documentation ranges, and IPv6 forms that wrap an IPv4 address - is refused."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_address(str(ip.ipv4_mapped))
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
        if ip in _NAT64 or ip in _NAT64_LOCAL:
            return False
    if (
        ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_private
    ):
        return False
    return ip.is_global


def _looks_like_an_address(host: str) -> bool:
    """An IP address in any spelling: dotted, one big number, hex, or IPv6 (also in brackets)."""
    if host.startswith("[") or ":" in host:
        return True
    if re.fullmatch(r"[0-9.]+", host) or re.match(r"0x[0-9a-f]+", host, re.IGNORECASE):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def validate_url(url: str, host: str) -> tuple[str, str]:
    """Check an address against the one host a source allows. Returns (host, path and query)."""
    if not url.lower().startswith("https://"):
        raise FetchRefused("bad_scheme")
    if len(url) > MAX_URL_LENGTH or any(ord(c) <= 0x20 or ord(c) >= 0x7F for c in url):
        raise FetchRefused("bad_url")
    parts = urlsplit(url)
    netloc = parts.netloc
    has_userinfo = "@" in netloc
    hostport = netloc.rpartition("@")[2]
    name, _, port = hostport.rpartition(":") if ":" in hostport else (hostport, "", "")
    if hostport.startswith("["):
        raise FetchRefused("ip_literal")
    name = name.lower()
    if _looks_like_an_address(name) or _looks_like_an_address(host.lower()):
        raise FetchRefused("ip_literal")
    if name != host.lower():
        raise FetchRefused("bad_host")
    if has_userinfo:
        raise FetchRefused("userinfo")
    if port not in ("", "443"):
        raise FetchRefused("bad_port")
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return name, target


# --- rate limiting -----------------------------------------------------------------------------


class HostLimiter:
    """At most one request per interval per host, and a ceiling per host per day.

    ``acquire`` waits out the interval (a worker job can afford to) and raises ``rate_limited``
    when the day's ceiling is reached. Share one instance between fetches, or it limits nothing.
    """

    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        daily_limit: int = 200,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self.daily_limit = daily_limit
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._days: dict[str, tuple[int, int]] = {}

    def acquire(self, host: str) -> None:
        day = int(self._clock() // 86_400)
        seen_day, count = self._days.get(host, (day, 0))
        if seen_day != day:
            count = 0
        if count >= self.daily_limit:
            raise FetchRefused("rate_limited")
        wait = self._last.get(host, float("-inf")) + self.min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last[host] = self._clock()
        self._days[host] = (day, count + 1)


# --- the real network --------------------------------------------------------------------------


def system_resolver(host: str) -> list[str]:
    """Every address the name resolves to (IPv4 and IPv6)."""
    found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in found))


class _PinnedConnection(http.client.HTTPSConnection):
    """Connects to a given address but verifies the certificate against the host NAME."""

    def __init__(
        self, host: str, port: int, ip: str, context: ssl.SSLContext, timeout: float
    ) -> None:
        super().__init__(host, port, timeout=timeout)
        self._ip = ip
        self._ctx = context

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


def real_transport(
    request: PinnedRequest, *, ssl_context: ssl.SSLContext | None = None
) -> TransportResponse:
    """One GET to the given address. The timeout covers the whole response, not each read."""
    context = ssl_context or ssl.create_default_context()
    deadline = time.monotonic() + request.timeout
    connection = _PinnedConnection(request.host, request.port, request.ip, context, request.timeout)
    try:
        connection.request("GET", request.target, headers=dict(request.headers))
        response = connection.getresponse()
        body = b""
        limit = request.max_bytes + 1
        while len(body) < limit:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(8192, limit - len(body)))
            if not chunk:
                break
            body += chunk
        headers = {name.lower(): value for name, value in response.getheaders()}
        return TransportResponse(
            response.status, headers, body[: request.max_bytes], len(body) > request.max_bytes
        )
    finally:
        connection.close()


# --- the fetch ---------------------------------------------------------------------------------


@dataclass
class _Site:
    host: str
    ip: str
    robots: urllib.robotparser.RobotFileParser | None = field(default=None)


def _resolve(host: str, resolver: Resolver) -> str:
    try:
        addresses = resolver(host)
    except OSError:
        raise FetchRefused("no_address") from None
    if not addresses:
        raise FetchRefused("no_address")
    if not all(is_public_address(address) for address in addresses):
        raise FetchRefused("private_address")
    return addresses[0]


def _send(
    site: _Site,
    target: str,
    transport: Transport,
    policy: FetchPolicy,
    limiter: HostLimiter | None,
) -> TransportResponse:
    if limiter is not None:
        limiter.acquire(site.host)
    request = PinnedRequest(
        ip=site.ip,
        host=site.host,
        target=target,
        headers={"User-Agent": policy.user_agent, "Accept-Encoding": "identity"},
        timeout=policy.timeout_s,
        max_bytes=policy.max_bytes,
    )
    try:
        return transport(request)
    except TimeoutError:
        raise FetchRefused("timeout") from None
    except Exception:  # noqa: BLE001 - whatever went wrong, the caller gets a fixed message
        raise FetchRefused("network_error") from None


def _read_robots(
    site: _Site, transport: Transport, policy: FetchPolicy, limiter: HostLimiter | None
) -> urllib.robotparser.RobotFileParser:
    response = _send(site, "/robots.txt", transport, policy, limiter)
    parser = urllib.robotparser.RobotFileParser()
    if 400 <= response.status < 500 and response.status != 429:
        parser.parse([])  # no rules: everything allowed (RFC 9309)
        return parser
    if response.status != 200 or response.truncated:
        raise FetchRefused("robots_unavailable")
    parser.parse(response.body.decode("utf-8", errors="ignore").splitlines())
    return parser


def fetch(
    url: str,
    *,
    host: str,
    resolver: Resolver = system_resolver,
    transport: Transport = real_transport,
    policy: FetchPolicy = FetchPolicy(),  # noqa: B008 - frozen, shared on purpose
    limiter: HostLimiter | None = None,
) -> FetchResult:
    """Fetch one page from ``host`` (the source's host). Raises ``FetchRefused`` otherwise.

    A page that exists but says "not found" or "busy" is returned with its status; deciding what
    that means belongs to the caller's parser. ``limiter`` is shared by the caller."""
    current = url
    site: _Site | None = None
    for hop in range(policy.max_redirects + 1):
        name, target = validate_url(current, host)
        if site is None:
            site = _Site(name, _resolve(name, resolver))
            site.robots = _read_robots(site, transport, policy, limiter)
        else:
            site = _Site(name, _resolve(name, resolver), site.robots)
        assert site.robots is not None  # noqa: S101 - set above on the first hop
        if not site.robots.can_fetch(ROBOTS_TOKEN, f"https://{name}{target}"):
            raise FetchRefused("robots_disallowed")
        response = _send(site, target, transport, policy, limiter)
        if response.status in REDIRECT_STATUSES:
            if hop >= policy.max_redirects:
                raise FetchRefused("too_many_redirects")
            location = response.headers.get("location", "")
            if not location or any(ord(c) <= 0x20 or ord(c) >= 0x7F for c in location):
                raise FetchRefused("bad_redirect")
            if location.startswith("//"):
                raise FetchRefused("bad_scheme")
            current = urljoin(current, location)
            continue
        if response.truncated:
            raise FetchRefused("too_large")
        if response.headers.get("content-encoding", "identity").strip().lower() not in (
            "",
            "identity",
        ):
            raise FetchRefused("bad_encoding")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in policy.content_types:
            raise FetchRefused("bad_content_type")
        return FetchResult(response.status, current, content_type, response.body, site.ip)
    raise FetchRefused("too_many_redirects")  # unreachable: the loop returns or raises
