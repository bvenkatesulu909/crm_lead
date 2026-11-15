"""The form search of the hardened fetcher (ADR 0019, Amendment A, step WC6a).

A registry whose search is an old web form: GET the source's fixed page, POST the form back to the
SAME path on the SAME pinned address with only the allow-listed hidden fields the page sent, the
query and the submit button. Everything is tested without the internet: a fake resolver and a fake
transport play the server."""

from dataclasses import dataclass, field
from urllib.parse import parse_qsl

import pytest

from app.core.webfetch import (
    MAX_FIELD_BYTES,
    FetchPolicy,
    FetchRefused,
    FormSpec,
    HostLimiter,
    PinnedRequest,
    TransportResponse,
    build_form,
    form_search,
)

HOST = "rera.example.org"
PATH = "/Views/Search.aspx"
PUBLIC_IP = "93.184.216.34"
SPEC = FormSpec(
    path=PATH,
    query_field="ctl00$Main$txtName",
    submit=("ctl00$Main$btnSubmit", "Search"),
    hidden_fields=("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__EVENTTARGET"),
    required=("__VIEWSTATE", "__EVENTVALIDATION"),
)
QUERY = "P12250106962"


def page(
    *,
    action: str = "./Search.aspx",
    method: str = "post",
    hidden: dict[str, str] | None = None,
    before: str = "",
    after: str = "",
) -> str:
    fields = (
        hidden
        if hidden is not None
        else {
            "__VIEWSTATE": "abc+/=",
            "__VIEWSTATEGENERATOR": "C0FFEE",
            "__EVENTVALIDATION": "xyz&amp;1",
            "__EVENTTARGET": "",
        }
    )
    inputs = "".join(
        f'<input type="hidden" name="{name}" id="{name}" value="{value}" />'
        for name, value in fields.items()
    )
    return (
        f'<html><body>{before}<form method="{method}" action="{action}" id="HomeForm">'
        f'{inputs}<input type="text" name="ctl00$Main$txtName" value="typed by the page" />'
        f'<input type="hidden" name="__SECRET_EXTRA" value="must-not-be-sent" />'
        f"</form>{after}</body></html>"
    )


def html(body: str, *, status: int = 200, **headers: str) -> TransportResponse:
    merged = {"content-type": "text/html; charset=utf-8", **headers}
    return TransportResponse(status, merged, body.encode(), False)


RESULTS = "<html><table><tr><td>P12250106962</td><td>Tower A</td></tr></table></html>"


@dataclass
class Net:
    addresses: list[str] = field(default_factory=lambda: [PUBLIC_IP])
    robots: TransportResponse = field(
        default_factory=lambda: TransportResponse(404, {"content-type": "text/html"}, b"", False)
    )
    get: TransportResponse = field(default_factory=lambda: html(page()))
    post: TransportResponse = field(default_factory=lambda: html(RESULTS))
    requests: list[PinnedRequest] = field(default_factory=list)

    def resolver(self, host: str) -> list[str]:
        return list(self.addresses)

    def transport(self, request: PinnedRequest) -> TransportResponse:
        self.requests.append(request)
        if request.target == "/robots.txt":
            return self.robots
        return self.post if request.method == "POST" else self.get

    def posted(self) -> list[tuple[str, str]]:
        [post] = [r for r in self.requests if r.method == "POST"]
        assert post.body is not None
        return parse_qsl(post.body.decode("ascii"), keep_blank_values=True)


def run(net: Net, query: str = QUERY, **options: object):  # noqa: ANN201
    return form_search(
        SPEC,
        query,
        host=HOST,
        resolver=net.resolver,
        transport=net.transport,
        **options,  # type: ignore[arg-type]
    )


# --- the happy path ------------------------------------------------------------------------------


def test_the_form_is_read_then_posted_back_to_the_same_page() -> None:
    net = Net()
    result = run(net)
    assert result.status == 200 and result.body == RESULTS.encode()
    assert result.final_url == f"https://{HOST}{PATH}" and result.content_type == "text/html"
    assert [(r.method, r.target) for r in net.requests] == [
        ("GET", "/robots.txt"),
        ("GET", PATH),
        ("POST", PATH),
    ]
    # Every request goes to the one address we checked, for the one host.
    assert {(r.ip, r.host, r.port) for r in net.requests} == {(PUBLIC_IP, HOST, 443)}


def test_only_the_allowed_hidden_fields_the_query_and_the_button_are_sent() -> None:
    net = Net()
    run(net)
    assert net.posted() == [
        ("__VIEWSTATE", "abc+/="),
        ("__VIEWSTATEGENERATOR", "C0FFEE"),
        ("__EVENTVALIDATION", "xyz&1"),  # the page's &amp; is read once, then encoded again
        ("__EVENTTARGET", ""),
        ("ctl00$Main$txtName", QUERY),  # the page's own text in that box is never sent
        ("ctl00$Main$btnSubmit", "Search"),
    ]


def test_the_post_carries_only_our_headers_and_no_cookie() -> None:
    net = Net()
    run(net)
    post = net.requests[-1]
    assert post.headers == {
        "User-Agent": "crm-lead-webcheck/1.0",
        "Accept-Encoding": "identity",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    assert all(r.body is None for r in net.requests[:-1])


def test_an_absolute_action_on_the_same_host_is_the_same_form() -> None:
    net = Net(get=html(page(action=f"https://{HOST}{PATH}")))
    assert run(net).status == 200


def test_the_first_matching_form_is_used_and_other_forms_are_ignored() -> None:
    other = (
        '<form method="post" action="/login">'
        '<input type="hidden" name="__VIEWSTATE" value="LOGIN" /></form>'
    )
    net = Net(get=html(page(before=other, after=other)))
    run(net)
    assert dict(net.posted())["__VIEWSTATE"] == "abc+/="


# --- the form must be the expected one -----------------------------------------------------------


@pytest.mark.parametrize(
    "changed",
    [
        page(action="./Other.aspx"),  # posts to another page
        page(action="https://evil.example/Views/Search.aspx"),  # posts to another host
        page(method="get"),  # not a POST form
        "<html><body>No form here.</body></html>",
        page(hidden={"__VIEWSTATE": "only this"}),  # a required field is missing
    ],
)
def test_a_form_that_is_not_the_expected_one_is_refused_before_posting(changed: str) -> None:
    net = Net(get=html(changed))
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "form_changed"
    assert all(r.method == "GET" for r in net.requests)


def test_a_page_that_is_not_ok_counts_as_a_changed_form() -> None:
    net = Net(get=html(page(), status=500))
    with pytest.raises(FetchRefused, match="not as expected"):
        run(net)
    assert all(r.method == "GET" for r in net.requests)


def test_a_huge_hidden_field_is_refused() -> None:
    big = "a" * (MAX_FIELD_BYTES + 1)
    fields = {"__VIEWSTATE": big, "__EVENTVALIDATION": "x"}
    net = Net(get=html(page(hidden=fields)))
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "form_too_large"


def test_fields_that_are_large_together_are_refused() -> None:
    near = "a" * (MAX_FIELD_BYTES - 10)
    fields = {"__VIEWSTATE": near, "__EVENTVALIDATION": near, "__VIEWSTATEGENERATOR": near}
    net = Net(get=html(page(hidden=fields)))
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "form_too_large"


@pytest.mark.parametrize("query", ["", "P1\nHost: evil", "P1\r", "x" * 201, "a\x00b", "a\x7fb"])
def test_a_bad_query_is_refused_and_nothing_is_posted(query: str) -> None:
    net = Net()
    with pytest.raises(FetchRefused) as refused:
        run(net, query)
    assert refused.value.code == "bad_query"
    assert all(r.method == "GET" for r in net.requests)


def test_a_query_with_form_characters_cannot_add_a_field() -> None:
    net = Net()
    run(net, "P1&__EVENTTARGET=evil")
    sent = net.posted()
    assert ("ctl00$Main$txtName", "P1&__EVENTTARGET=evil") in sent
    assert ("__EVENTTARGET", "evil") not in sent


# --- every protection of the plain fetch still applies -------------------------------------------


def test_a_private_address_is_refused_before_anything_is_sent() -> None:
    net = Net(addresses=[PUBLIC_IP, "10.0.0.5"])
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "private_address" and net.requests == []


def test_robots_txt_is_obeyed() -> None:
    rules = b"User-agent: *\nDisallow: /Views/\n"
    net = Net(robots=TransportResponse(200, {"content-type": "text/plain"}, rules, False))
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "robots_disallowed"
    assert [r.target for r in net.requests] == ["/robots.txt"]


@pytest.mark.parametrize("step", ["get", "post"])
def test_a_redirect_is_never_followed(step: str) -> None:
    moved = TransportResponse(302, {"location": "https://evil.example/"}, b"", False)
    net = Net(get=moved) if step == "get" else Net(post=moved)
    with pytest.raises(FetchRefused) as refused:
        run(net)
    assert refused.value.code == "bad_redirect"
    assert len(net.requests) == (2 if step == "get" else 3)


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (
            TransportResponse(200, {"content-type": "application/json"}, b"{}", False),
            "bad_content_type",
        ),
        (TransportResponse(200, {"content-type": "text/plain"}, b"x", False), "bad_content_type"),
        (TransportResponse(200, {"content-type": "text/html"}, b"x", True), "too_large"),
        (
            TransportResponse(
                200, {"content-type": "text/html", "content-encoding": "gzip"}, b"x", False
            ),
            "bad_encoding",
        ),
    ],
)
def test_an_answer_that_is_not_a_small_plain_html_page_is_refused(
    answer: TransportResponse, code: str
) -> None:
    with pytest.raises(FetchRefused) as refused:
        run(Net(post=answer))
    assert refused.value.code == code


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_one_deadline_covers_the_whole_check() -> None:
    clock = Clock()
    net = Net()
    original = net.transport

    def slow(request: PinnedRequest) -> TransportResponse:
        clock.now += 6  # each request takes 6 s of the 10 s
        return original(request)

    with pytest.raises(FetchRefused) as refused:
        form_search(SPEC, QUERY, host=HOST, resolver=net.resolver, transport=slow, clock=clock)
    assert refused.value.code == "timeout"
    assert [r.method for r in net.requests] == ["GET", "GET"]  # the POST is never sent


def test_the_time_left_is_what_a_request_may_use() -> None:
    clock = Clock()
    net = Net()
    original = net.transport

    def slow(request: PinnedRequest) -> TransportResponse:
        clock.now += 3
        return original(request)

    form_search(SPEC, QUERY, host=HOST, resolver=net.resolver, transport=slow, clock=clock)
    assert [round(r.timeout, 3) for r in net.requests] == [10.0, 7.0, 4.0]


def test_the_limiter_counts_and_spaces_every_request() -> None:
    clock = Clock()
    limiter = HostLimiter(min_interval=1.0, daily_limit=10, clock=clock, sleep=clock.sleep)
    net = Net()
    run(net, limiter=limiter, clock=clock)
    assert clock.slept == [1.0, 1.0]  # robots -> page -> answer, one second apart
    tight = HostLimiter(min_interval=0, daily_limit=2, clock=clock, sleep=clock.sleep)
    net2 = Net()
    with pytest.raises(FetchRefused) as refused:
        run(net2, limiter=tight, clock=clock)
    assert refused.value.code == "rate_limited"
    assert [r.method for r in net2.requests] == ["GET", "GET"]


def test_the_policy_still_limits_the_size_of_every_answer() -> None:
    net = Net()
    run(net, policy=FetchPolicy(max_bytes=5000))
    assert {r.max_bytes for r in net.requests} == {5000}


# --- the form spec itself ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"query_field": "q\nx"},
        {"query_field": ""},
        {"submit": ("bad name", "Search")},
        {"hidden_fields": ("__VIEWSTATE", "a b")},
        {"required": ("__NOT_ALLOWED",)},
        {"path": "Views/Search.aspx"},
        {"path": "/Views/Search.aspx?x=1"},
        {"path": "/Views/Search.aspx#top"},
    ],
)
def test_a_badly_written_form_spec_is_refused(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "path": PATH,
        "query_field": "q",
        "submit": ("go", "Search"),
        "hidden_fields": ("__VIEWSTATE",),
        "required": ("__VIEWSTATE",),
    }
    values.update(changes)
    with pytest.raises(ValueError):
        FormSpec(**values)  # type: ignore[arg-type]


def test_build_form_alone_adds_nothing_the_spec_does_not_name() -> None:
    body = build_form(page().encode(), f"https://{HOST}{PATH}", SPEC, QUERY).decode()
    assert "__SECRET_EXTRA" not in body and "typed+by+the+page" not in body
