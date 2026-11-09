"""The hardened page fetcher (ADR 0019): the only code that fetches a web page for a user.

It refuses by default. A page may be fetched only from the host a source names (the model and the
user never give an address); only over https on port 443; only when EVERY address the name
resolves to is public, and the connection is then made to that address (a second DNS answer
cannot swap the machine after the check); only when robots.txt allows it; with a time limit, a
size limit, no cookies or credentials, and no compressed bodies. Redirects are followed only
inside the same host and every hop is checked again.

``form_search`` (ADR 0019, Amendment A) is the one other shape: a registry whose search is an old
web form. It GETs the source's fixed page and POSTs that form back to the SAME path on the SAME
pinned address, carrying only the hidden fields the page itself sent (from the source's allow-list,
size-capped), the one query field and the submit button. No redirect is followed, and one deadline
covers the whole check.

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
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

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
    "form_changed": "The site's search form is not as expected.",
    "form_too_large": "The site's search form is larger than the limit.",
    "bad_query": "The search text is not valid.",
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
    method: str = "GET"
    body: bytes | None = None


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
    """One request (a GET, or the form search's POST) to the given address. The timeout covers
    the whole response, not each read."""
    context = ssl_context or ssl.create_default_context()
    deadline = time.monotonic() + request.timeout
    connection = _PinnedConnection(request.host, request.port, request.ip, context, request.timeout)
    try:
        if request.method not in ("GET", "POST"):
            raise ValueError("only GET and POST are sent")
        connection.request(
            request.method, request.target, body=request.body, headers=dict(request.headers)
        )
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
    *,
    form: bytes | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> TransportResponse:
    if limiter is not None:
        limiter.acquire(site.host)
    timeout = policy.timeout_s
    if deadline is not None:
        timeout = min(timeout, deadline - clock())
        if timeout <= 0:
            raise FetchRefused("timeout")
    headers = {"User-Agent": policy.user_agent, "Accept-Encoding": "identity"}
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = PinnedRequest(
        ip=site.ip,
        host=site.host,
        target=target,
        headers=headers,
        timeout=timeout,
        max_bytes=policy.max_bytes,
        method="GET" if form is None else "POST",
        body=form,
    )
    try:
        return transport(request)
    except TimeoutError:
        raise FetchRefused("timeout") from None
    except Exception:  # noqa: BLE001 - whatever went wrong, the caller gets a fixed message
        raise FetchRefused("network_error") from None


def _read_robots(
    site: _Site,
    transport: Transport,
    policy: FetchPolicy,
    limiter: HostLimiter | None,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> urllib.robotparser.RobotFileParser:
    response = _send(
        site, "/robots.txt", transport, policy, limiter, deadline=deadline, clock=clock
    )
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


# --- the form search (ADR 0019, Amendment A) ---------------------------------------------------

_FIELD_NAME = re.compile(r"^[A-Za-z0-9_$.:-]{1,100}$")
MAX_FIELD_BYTES = 64 * 1024
MAX_FORM_BYTES = 128 * 1024
MAX_QUERY_LENGTH = 200


@dataclass(frozen=True)
class FormSpec:
    """How one source's search form is filled. Everything here is fixed in the source catalogue;
    nothing comes from a person or a model except the (already validated) query."""

    path: str  # the page and the form's target, e.g. "/RERA/Views/Reports/Search.aspx"
    query_field: str  # the text box the query goes into
    submit: tuple[str, str]  # the button's name and value
    hidden_fields: tuple[str, ...]  # the only hidden fields that may be sent back
    required: tuple[str, ...] = ()  # hidden fields the page must have, or it has changed

    def __post_init__(self) -> None:
        names = [self.query_field, self.submit[0], *self.hidden_fields, *self.required]
        if not all(_FIELD_NAME.match(name) for name in names):
            raise ValueError("a form field name is not allowed")
        if not set(self.required) <= set(self.hidden_fields):
            raise ValueError("a required field must also be allowed")
        if not self.path.startswith("/") or any(c in self.path for c in "?#\\ "):
            raise ValueError("the form path must be a plain absolute path")


class _FormReader(HTMLParser):
    """The hidden inputs of the first top-level POST form whose target is ``path``."""

    def __init__(self, page_url: str, path: str) -> None:
        super().__init__(convert_charrefs=True)
        self._page_url = page_url
        self._path = path
        self._depth = 0
        self._inside = False
        self.found = False
        self.fields: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "form":
            self._depth += 1
            target = urlsplit(urljoin(self._page_url, values.get("action", "")))
            if (
                self._depth == 1
                and not self.found
                and values.get("method", "get").lower() == "post"
                and target.netloc == urlsplit(self._page_url).netloc
                and target.path == self._path
            ):
                self._inside = True
                self.found = True
        elif tag == "input" and self._inside and values.get("type", "").lower() == "hidden":
            self.fields.append((values.get("name", ""), values.get("value", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self._inside = False


def build_form(page: bytes, page_url: str, spec: FormSpec, query: str) -> bytes:
    """The POST body: allow-listed hidden fields the page sent, the query, the submit button.
    Raises ``form_changed`` / ``form_too_large`` / ``bad_query``; never adds anything else."""
    if (
        not query
        or len(query) > MAX_QUERY_LENGTH
        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in query)
    ):
        raise FetchRefused("bad_query")
    reader = _FormReader(page_url, spec.path)
    reader.feed(page.decode("utf-8", errors="replace"))
    reader.close()
    if not reader.found:
        raise FetchRefused("form_changed")
    on_page: dict[str, str] = {}
    for name, value in reader.fields:
        on_page.setdefault(name, value)  # the first of a repeated name counts
    # The ONE place the allow-list is applied: nothing else of the page is ever sent.
    sent = {name: on_page[name] for name in spec.hidden_fields if name in on_page}
    if not set(spec.required) <= set(sent):
        raise FetchRefused("form_changed")
    if any(len(value.encode()) > MAX_FIELD_BYTES for value in sent.values()):
        raise FetchRefused("form_too_large")
    pairs = list(sent.items())
    pairs += [(spec.query_field, query), spec.submit]
    body = urlencode(pairs).encode("ascii")
    if len(body) > MAX_FORM_BYTES:
        raise FetchRefused("form_too_large")
    return body


def _accept(response: TransportResponse, policy: FetchPolicy) -> str:
    """The checks every answer of a form search must pass; returns its content type."""
    if response.status in REDIRECT_STATUSES:
        raise FetchRefused("bad_redirect")  # never followed in a form search
    if response.truncated:
        raise FetchRefused("too_large")
    if response.headers.get("content-encoding", "identity").strip().lower() not in (
        "",
        "identity",
    ):
        raise FetchRefused("bad_encoding")
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "text/html" or content_type not in policy.content_types:
        raise FetchRefused("bad_content_type")
    return content_type


def form_search(
    spec: FormSpec,
    query: str,
    *,
    host: str,
    resolver: Resolver = system_resolver,
    transport: Transport = real_transport,
    policy: FetchPolicy = FetchPolicy(),  # noqa: B008 - frozen, shared on purpose
    limiter: HostLimiter | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FetchResult:
    """Search a registry whose search is a web form: GET ``spec.path`` on ``host``, then POST the
    form back to the same path on the same pinned address. ``policy.timeout_s`` covers the whole
    check (robots.txt, the page and the answer together). Raises ``FetchRefused`` otherwise."""
    deadline = clock() + policy.timeout_s
    page_url = f"https://{host}{spec.path}"
    name, target = validate_url(page_url, host)
    site = _Site(name, _resolve(name, resolver))
    site.robots = _read_robots(site, transport, policy, limiter, deadline=deadline, clock=clock)
    if not site.robots.can_fetch(ROBOTS_TOKEN, page_url):
        raise FetchRefused("robots_disallowed")
    page = _send(site, target, transport, policy, limiter, deadline=deadline, clock=clock)
    _accept(page, policy)
    if page.status != 200:
        raise FetchRefused("form_changed")
    form = build_form(page.body, page_url, spec, query)
    answer = _send(
        site, target, transport, policy, limiter, form=form, deadline=deadline, clock=clock
    )
    content_type = _accept(answer, policy)
    return FetchResult(answer.status, page_url, content_type, answer.body, site.ip)
