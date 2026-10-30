"""The hardened fetcher (ADR 0019, step WC1): the only code that fetches a web page for a user.

Everything is tested without the internet: a fake resolver says what a host name resolves to, a
fake transport answers what the "server" says. The real transport is tested against a local TLS
server with a self-signed certificate (tests/test_webfetch_transport.py)."""

import re
from pathlib import Path

import pytest

from app.core.webfetch import (
    USER_AGENT,
    FetchPolicy,
    FetchRefused,
    HostLimiter,
    PinnedRequest,
    TransportResponse,
    fetch,
    is_public_address,
    validate_url,
)

HOST = "registry.example.org"
PUBLIC_IP = "93.184.216.34"


# --- which addresses are public ----------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1.2.3",
        "10.0.0.5",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",  # the cloud metadata service
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104 - an address the fetcher must refuse, not a bind
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "192.0.2.1",  # documentation range
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "ff02::1",
        "::ffff:127.0.0.1",  # an IPv4 address written as IPv6
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "2002:7f00:1::",  # 6to4 wrapping 127.0.0.1
        "64:ff9b::7f00:1",  # NAT64 wrapping 127.0.0.1
        "not-an-address",
        "",
        "93.184.216.34/32",
    ],
)
def test_addresses_that_are_not_public_are_refused(address: str) -> None:
    assert is_public_address(address) is False


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"]
)
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(address) is True


# --- which addresses may be asked for ----------------------------------------------------------


def test_a_plain_https_address_on_the_sources_host_is_accepted() -> None:
    assert validate_url(f"https://{HOST}/search?q=A123", HOST) == (HOST, "/search?q=A123")


def test_the_host_is_compared_without_case_and_a_standard_port_is_fine() -> None:
    assert validate_url(f"https://{HOST.upper()}:443/x", HOST)[0] == HOST


def test_an_address_without_a_path_gets_a_slash() -> None:
    assert validate_url(f"https://{HOST}", HOST) == (HOST, "/")


@pytest.mark.parametrize(
    ("url", "code"),
    [
        (f"http://{HOST}/x", "bad_scheme"),
        (f"ftp://{HOST}/x", "bad_scheme"),
        (f"file://{HOST}/etc/passwd", "bad_scheme"),
        ("javascript:alert(1)", "bad_scheme"),
        (f"//{HOST}/x", "bad_scheme"),
        (f"https://{HOST}:8443/x", "bad_port"),
        (f"https://{HOST}:80/x", "bad_port"),
        (f"https://user@{HOST}/x", "userinfo"),
        (f"https://user:secret@{HOST}/x", "userinfo"),
        ("https://other.example.org/x", "bad_host"),
        (f"https://{HOST}.evil.example/x", "bad_host"),
        (f"https://evil.example/{HOST}", "bad_host"),
        (f"https://{HOST}\\@evil.example/x", "bad_host"),
        (f"https://{HOST}%2f@evil.example/x", "bad_host"),
        ("https://127.0.0.1/x", "ip_literal"),
        ("https://[::1]/x", "ip_literal"),
        ("https://169.254.169.254/latest/meta-data", "ip_literal"),
        ("https://2130706433/x", "ip_literal"),  # 127.0.0.1 as one number
        (f"https://{HOST}/a b", "bad_url"),
        (f"https://{HOST}/a\r\nHost: evil", "bad_url"),
        (f"https://{HOST}/" + "a" * 2100, "bad_url"),
        ("", "bad_scheme"),
    ],
)
def test_addresses_that_could_lead_elsewhere_are_refused(url: str, code: str) -> None:
    with pytest.raises(FetchRefused) as refused:
        validate_url(url, HOST)
    assert refused.value.code == code


def test_a_source_host_that_is_an_address_is_refused() -> None:
    with pytest.raises(FetchRefused) as refused:
        validate_url("https://127.0.0.1/x", "127.0.0.1")
    assert refused.value.code == "ip_literal"


# --- the fetch itself, with a fake network ------------------------------------------------------


class Net:
    """A fake resolver + transport that records everything it was asked."""

    def __init__(self) -> None:
        self.resolved: list[str] = []
        self.requests: list[PinnedRequest] = []
        self.addresses: dict[str, list[str]] = {HOST: [PUBLIC_IP]}
        self.pages: dict[str, TransportResponse] = {}
        self.error: Exception | None = None

    def resolver(self, host: str) -> list[str]:
        self.resolved.append(host)
        if host not in self.addresses:
            raise OSError("no such host")
        return self.addresses[host]

    def transport(self, request: PinnedRequest) -> TransportResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.pages.get(request.target, ok("not found", status=404))


def ok(
    body: str = "<html>RERA A123 registered</html>",
    *,
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
    headers: dict[str, str] | None = None,
    truncated: bool = False,
) -> TransportResponse:
    merged = {"content-type": content_type, **(headers or {})}
    return TransportResponse(status, merged, body.encode(), truncated)


def run(net: Net, url: str = f"https://{HOST}/search?q=A123", **options: object):
    return fetch(url, host=HOST, resolver=net.resolver, transport=net.transport, **options)  # type: ignore[arg-type]


@pytest.fixture
def net() -> Net:
    n = Net()
    n.pages["/robots.txt"] = ok("User-agent: *\nAllow: /\n", content_type="text/plain")
    n.pages["/search?q=A123"] = ok()
    return n


def test_a_page_is_fetched_and_returned(net: Net) -> None:
    result = run(net)
    assert result.status == 200 and result.body == b"<html>RERA A123 registered</html>"
    assert result.final_url == f"https://{HOST}/search?q=A123"
    assert result.content_type == "text/html"
    assert result.address == PUBLIC_IP


def test_the_connection_goes_to_the_address_we_checked(net: Net) -> None:
    """Resolved once; every request is pinned to that address, so a second DNS answer cannot
    swap in a different machine after the check."""
    run(net)
    assert net.resolved == [HOST]
    assert {request.ip for request in net.requests} == {PUBLIC_IP}
    assert {request.host for request in net.requests} == {HOST}


def test_the_request_carries_no_cookies_or_credentials(net: Net) -> None:
    run(net)
    for request in net.requests:
        names = {name.lower() for name in request.headers}
        assert not names & {"cookie", "authorization", "proxy-authorization"}
        assert request.headers["User-Agent"] == USER_AGENT
        assert request.headers["Accept-Encoding"] == "identity"  # no compressed bombs


def test_the_limits_come_from_the_policy(net: Net) -> None:
    run(net, policy=FetchPolicy(timeout_s=3.0, max_bytes=5000))
    assert all(r.timeout <= 3.0 and r.max_bytes == 5000 for r in net.requests)


def test_the_default_limits_are_ten_seconds_and_one_megabyte() -> None:
    policy = FetchPolicy()
    assert policy.timeout_s == 10.0 and policy.max_bytes == 1_000_000
    assert policy.max_redirects == 2


def test_a_name_that_resolves_to_a_private_address_is_refused_before_any_request(
    net: Net,
) -> None:
    net.addresses[HOST] = ["10.0.0.7"]
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "private_address" and net.requests == []


def test_one_private_answer_among_public_ones_refuses_the_whole_name(net: Net) -> None:
    net.addresses[HOST] = [PUBLIC_IP, "169.254.169.254"]
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "private_address" and net.requests == []


def test_a_name_that_does_not_resolve_is_refused(net: Net) -> None:
    net.addresses[HOST] = []
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "no_address"
    del net.addresses[HOST]  # the resolver now raises
    with pytest.raises(FetchRefused) as again:
        run(net)
    assert again.value.code == "no_address"


def test_an_address_for_another_host_is_refused_without_resolving(net: Net) -> None:
    with pytest.raises(FetchRefused) as refused:
        run(net, "https://evil.example/x")
    assert refused.value.code == "bad_host" and net.resolved == [] and net.requests == []


# robots.txt


def test_robots_is_read_first(net: Net) -> None:
    run(net)
    assert [r.target for r in net.requests] == ["/robots.txt", "/search?q=A123"]


def test_a_page_that_robots_forbids_is_not_requested(net: Net) -> None:
    net.pages["/robots.txt"] = ok("User-agent: *\nDisallow: /search\n", content_type="text/plain")
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "robots_disallowed"
    assert [r.target for r in net.requests] == ["/robots.txt"]


def test_a_rule_that_names_this_crawler_is_honoured(net: Net) -> None:
    net.pages["/robots.txt"] = ok(
        "User-agent: crm-lead-webcheck\nDisallow: /\n", content_type="text/plain"
    )
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "robots_disallowed"


def test_a_rule_for_other_pages_does_not_block_this_one(net: Net) -> None:
    net.pages["/robots.txt"] = ok("User-agent: *\nDisallow: /admin\n", content_type="text/plain")
    assert run(net).status == 200


def test_no_robots_file_means_allowed(net: Net) -> None:
    net.pages["/robots.txt"] = ok("missing", status=404)
    assert run(net).status == 200


def test_a_robots_file_that_cannot_be_read_blocks_the_fetch(net: Net) -> None:
    """A server error is not permission: we do not guess."""
    net.pages["/robots.txt"] = ok("oops", status=503)
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "robots_unavailable"
    assert [r.target for r in net.requests] == ["/robots.txt"]


# redirects


def test_a_redirect_on_the_same_host_is_followed(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("", status=301, headers={"location": "/projects/A123"})
    net.pages["/projects/A123"] = ok("<html>project</html>")
    result = run(net)
    assert result.body == b"<html>project</html>"
    assert result.final_url == f"https://{HOST}/projects/A123"


def test_an_absolute_redirect_on_the_same_host_is_followed(net: Net) -> None:
    net.pages["/search?q=A123"] = ok(
        "", status=302, headers={"location": f"https://{HOST}/projects/A123"}
    )
    net.pages["/projects/A123"] = ok("<html>project</html>")
    assert run(net).final_url == f"https://{HOST}/projects/A123"


@pytest.mark.parametrize(
    ("location", "code"),
    [
        ("https://evil.example/x", "bad_host"),
        ("http://" + HOST + "/x", "bad_scheme"),
        ("https://169.254.169.254/latest", "ip_literal"),
        ("//evil.example/x", "bad_scheme"),
    ],
)
def test_a_redirect_that_leaves_the_host_or_downgrades_is_refused(
    net: Net, location: str, code: str
) -> None:
    net.pages["/search?q=A123"] = ok("", status=302, headers={"location": location})
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == code


def test_a_redirect_without_a_target_is_refused(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("", status=302)
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "bad_redirect"


def test_too_many_redirects_are_refused(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("", status=302, headers={"location": "/a"})
    net.pages["/a"] = ok("", status=302, headers={"location": "/b"})
    net.pages["/b"] = ok("", status=302, headers={"location": "/c"})
    net.pages["/c"] = ok("done")
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "too_many_redirects"


def test_every_hop_is_resolved_and_checked_again(net: Net) -> None:
    """A host that answers with a public address first and a private one later is caught."""
    net.pages["/search?q=A123"] = ok("", status=302, headers={"location": "/next"})
    answers = iter([[PUBLIC_IP], ["10.0.0.9"]])  # the first hop, then the one after the redirect
    seen: list[str] = []

    def rebinding(host: str) -> list[str]:
        seen.append(host)
        return next(answers)

    with pytest.raises(FetchRefused) as refused:
        fetch(
            f"https://{HOST}/search?q=A123",
            host=HOST,
            resolver=rebinding,
            transport=net.transport,
        )
    assert refused.value.code == "private_address"
    assert "/next" not in [r.target for r in net.requests]


# content


@pytest.mark.parametrize(
    "content_type", ["text/html", "text/html; charset=utf-8", "application/json", "text/plain"]
)
def test_text_like_content_types_are_accepted(net: Net, content_type: str) -> None:
    net.pages["/search?q=A123"] = ok("x", content_type=content_type)
    assert run(net).content_type == content_type.split(";")[0]


@pytest.mark.parametrize(
    "content_type",
    ["application/octet-stream", "image/png", "application/pdf", "application/zip", "text/csv"],
)
def test_other_content_types_are_refused(net: Net, content_type: str) -> None:
    net.pages["/search?q=A123"] = ok("x", content_type=content_type)
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "bad_content_type"


def test_a_response_without_a_content_type_is_refused(net: Net) -> None:
    net.pages["/search?q=A123"] = TransportResponse(200, {}, b"x", False)
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "bad_content_type"


def test_an_encoded_body_is_refused(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("x", headers={"content-encoding": "gzip"})
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "bad_encoding"


def test_a_body_over_the_size_limit_is_refused_not_cut(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("x" * 10, truncated=True)
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "too_large"


def test_a_page_that_says_not_found_is_returned_as_it_is(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("<html>No such project</html>", status=404)
    result = run(net)
    assert result.status == 404 and b"No such project" in result.body


def test_a_server_error_is_returned_as_it_is(net: Net) -> None:
    net.pages["/search?q=A123"] = ok("busy", status=503, content_type="text/plain")
    assert run(net).status == 503


# failures of the network


def test_a_timeout_becomes_a_refusal(net: Net) -> None:
    net.error = TimeoutError("slow")
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "timeout"


@pytest.mark.parametrize("error", [ConnectionResetError("reset"), OSError("unreachable")])
def test_a_network_error_becomes_a_refusal(net: Net, error: Exception) -> None:
    net.error = error
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "network_error"


def test_a_refusal_does_not_repeat_what_the_server_said(net: Net) -> None:
    net.error = OSError("secret internal detail 10.1.2.3")
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert "10.1.2.3" not in str(refused.value) and "secret" not in str(refused.value)


# --- the limiter --------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += seconds


def limiter(clock: Clock, **options: object) -> HostLimiter:
    return HostLimiter(clock=clock.time, sleep=clock.sleep, **options)  # type: ignore[arg-type]


def test_a_second_request_to_the_same_host_waits_for_the_interval() -> None:
    clock = Clock()
    gate = limiter(clock, min_interval=1.0)
    gate.acquire(HOST)
    assert clock.slept == []
    clock.now += 0.4
    gate.acquire(HOST)
    assert clock.slept == [0.6]


def test_a_request_after_the_interval_does_not_wait() -> None:
    clock = Clock()
    gate = limiter(clock, min_interval=1.0)
    gate.acquire(HOST)
    clock.now += 1.5
    gate.acquire(HOST)
    assert clock.slept == []


def test_hosts_are_limited_separately() -> None:
    clock = Clock()
    gate = limiter(clock, min_interval=1.0)
    gate.acquire(HOST)
    gate.acquire("other.example.org")
    assert clock.slept == []


def test_the_daily_ceiling_refuses_further_requests() -> None:
    clock = Clock()
    gate = limiter(clock, min_interval=0.0, daily_limit=3)
    for _ in range(3):
        gate.acquire(HOST)
    with pytest.raises(FetchRefused) as refused:
        gate.acquire(HOST)
    assert refused.value.code == "rate_limited"


def test_the_ceiling_starts_again_the_next_day() -> None:
    clock = Clock()
    gate = limiter(clock, min_interval=0.0, daily_limit=1)
    gate.acquire(HOST)
    with pytest.raises(FetchRefused):
        gate.acquire(HOST)
    clock.now += 86_400
    gate.acquire(HOST)


def test_every_request_of_a_fetch_goes_through_the_limiter(net: Net) -> None:
    """robots.txt and the page are both requests to the host."""
    clock = Clock()
    run(net, limiter=limiter(clock, min_interval=1.0))
    assert len(net.requests) == 2 and clock.slept == [1.0]


def test_a_fetch_over_the_ceiling_makes_no_request(net: Net) -> None:
    clock = Clock()
    gate = limiter(clock, min_interval=0.0, daily_limit=0)
    with pytest.raises(FetchRefused) as refused:
        run(net, limiter=gate)
    assert refused.value.code == "rate_limited" and net.requests == []


# --- the only fetcher ---------------------------------------------------------------------------

APP = Path(__file__).resolve().parents[1] / "app"
HTTP_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:httpx|requests|urllib\.request|urllib3|http\.client|aiohttp"
    r"|boto3|botocore)\b",
    re.MULTILINE,
)
# Code that already talks to a fixed, configured service (never to an address a user chose).
KNOWN_CLIENTS = {
    "core/auth/identity_admin.py",  # Keycloak admin API
    "core/storage.py",  # the file store
    "modules/assistant/llm.py",  # the AI providers
    "modules/voice/provider.py",  # the voice provider
    "core/webfetch.py",  # the one fetcher for pages (this step)
}


def clients() -> set[str]:
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        if HTTP_IMPORT.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(APP).as_posix())
    return found


def test_no_new_code_fetches_over_http_on_its_own() -> None:
    """A page for a user is fetched by app.core.webfetch only (ADR 0019). A new module that
    imports an HTTP client must either use the fetcher or be added here on purpose."""
    assert clients() <= KNOWN_CLIENTS, sorted(clients() - KNOWN_CLIENTS)


def test_the_fetcher_itself_is_one_of_them() -> None:
    assert "core/webfetch.py" in clients() or (
        "core/webfetch.py" in {p.relative_to(APP).as_posix() for p in APP.rglob("*.py")}
    )
