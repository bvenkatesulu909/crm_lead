"""Payment links, pure part 2 (ADR 0031, UP2): reading a webhook body and the real Razorpay client,
which is tested against a fake transport - no network, no key."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.modules.payment_links import webhook
from app.modules.payment_links.provider import ProviderError
from app.modules.payment_links.razorpay import BASE_URL, RazorpayProvider

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def body(event: str = "payment_link.paid", **over: Any) -> bytes:
    data: dict[str, Any] = {
        "event": event,
        "payload": {
            "payment_link": {"entity": {"id": "plink_Abc123", "status": "paid"}},
            "payment": {
                "entity": {
                    "id": "pay_XyZ789",
                    "amount": 21416,
                    "currency": "INR",
                    "method": "upi",
                    "email": "buyer@example.test",
                    "contact": "+919999999999",
                    "vpa": "buyer@upi",
                }
            },
        },
    }
    data.update(over)
    return json.dumps(data).encode()


# --- reading a webhook -----------------------------------------------------------------------


def test_a_paid_event_gives_the_link_and_the_facts() -> None:
    parsed = webhook.parse_event(body())
    assert parsed is not None
    assert (parsed.event_type, parsed.link_id) == ("payment_link.paid", "plink_Abc123")
    assert parsed.facts == {"payment_id": "pay_XyZ789", "amount_paise": 21416, "currency": "INR"}


def test_no_personal_or_instrument_data_is_copied_out() -> None:
    parsed = webhook.parse_event(body())
    assert parsed is not None
    kept = json.dumps(parsed.facts)
    for secret in ("buyer@example.test", "+919999999999", "buyer@upi"):
        assert secret not in kept


@pytest.mark.parametrize("event", ["payment_link.expired", "payment_link.cancelled"])
def test_expired_and_cancelled_events_are_read(event: str) -> None:
    parsed = webhook.parse_event(body(event))
    assert parsed is not None and parsed.event_type == event


@pytest.mark.parametrize(
    "event", ["payment.captured", "order.paid", "refund.created", "payment_link.partially_paid", ""]
)
def test_other_events_are_not_acted_on(event: str) -> None:
    assert webhook.parse_event(body(event)) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'"payment_link.paid"',
        b'{"event": "payment_link.paid"}',
        b'{"event": "payment_link.paid", "payload": []}',
        b'{"event": "payment_link.paid", "payload": {"payment_link": {"entity": {}}}}',
        b'{"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": 5}}}}',
        b'{"event": ["payment_link.paid"], "payload": {}}',
    ],
)
def test_a_body_in_the_wrong_shape_is_ignored_not_an_error(raw: bytes) -> None:
    assert webhook.parse_event(raw) is None


def test_an_id_that_is_too_long_is_ignored() -> None:
    long_id = "p" * 61
    raw = body(payload={"payment_link": {"entity": {"id": long_id}}})
    assert webhook.parse_event(raw) is None


def test_a_boolean_or_text_amount_is_not_a_number_of_paise() -> None:
    for amount in (True, "21416", 21416.5, None):
        raw = body(
            payload={
                "payment_link": {"entity": {"id": "plink_1"}},
                "payment": {"entity": {"id": "pay_1", "amount": amount, "currency": "INR"}},
            }
        )
        parsed = webhook.parse_event(raw)
        assert parsed is not None and parsed.facts["amount_paise"] is None


# --- the real client -------------------------------------------------------------------------


class Recorder:
    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.payload = payload if payload is not None else {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.payload, bytes):
            return httpx.Response(self.status, content=self.payload)
        return httpx.Response(self.status, json=self.payload)


def provider(recorder: Recorder) -> RazorpayProvider:
    client = httpx.Client(transport=httpx.MockTransport(recorder), follow_redirects=False)
    return RazorpayProvider("rzp_test_key", "key-secret-value", client=client)


def create(p: RazorpayProvider, **over: Any):
    values: dict[str, Any] = {
        "reference_id": "ref1",
        "amount_paise": 21416,
        "currency": "INR",
        "description": "Invoice 7",
        "expires_at": NOW,
        "notes": {"invoice_id": "abc"},
    }
    values.update(over)
    return p.create_link(**values)


GOOD = {"id": "plink_Abc123", "short_url": "https://rzp.io/i/abc"}


def test_a_link_is_created_with_the_documented_fields() -> None:
    rec = Recorder(payload=GOOD)
    link = create(provider(rec))
    assert (link.provider_link_id, link.short_url) == ("plink_Abc123", "https://rzp.io/i/abc")
    [request] = rec.requests
    assert request.method == "POST" and str(request.url) == f"{BASE_URL}/payment_links"
    sent = json.loads(request.content)
    assert sent == {
        "amount": 21416,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": "ref1",
        "description": "Invoice 7",
        "expire_by": int(NOW.timestamp()),
        "reminder_enable": False,
        "notes": {"invoice_id": "abc"},
    }


def test_the_key_goes_in_the_auth_header_and_nowhere_else() -> None:
    rec = Recorder(payload=GOOD)
    create(provider(rec))
    [request] = rec.requests
    assert request.headers["authorization"].startswith("Basic ")
    assert b"key-secret-value" not in request.content
    assert "key-secret-value" not in str(request.url)


def test_no_customer_details_are_sent() -> None:
    rec = Recorder(payload=GOOD)
    create(provider(rec))
    assert "customer" not in json.loads(rec.requests[0].content)


@pytest.mark.parametrize("status", [400, 401, 429, 500, 302])
def test_a_refusal_becomes_a_short_error_without_the_body(status: int) -> None:
    rec = Recorder(status, {"error": {"description": "secret detail rzp_test_key"}})
    with pytest.raises(ProviderError) as refused:
        create(provider(rec))
    assert str(status) in str(refused.value)
    assert "secret detail" not in str(refused.value) and "rzp_test_key" not in str(refused.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": "plink_1"},
        {"id": "plink_1", "short_url": "http://insecure.example/x"},
        {"id": "plink_1", "short_url": 5},
        {"id": "../x", "short_url": "https://rzp.io/i/x"},
        {"id": "", "short_url": "https://rzp.io/i/x"},
        [],
    ],
)
def test_an_answer_in_the_wrong_shape_is_refused(payload: Any) -> None:
    with pytest.raises(ProviderError):
        create(provider(Recorder(payload=payload)))


def test_an_answer_that_is_not_json_is_refused() -> None:
    with pytest.raises(ProviderError):
        create(provider(Recorder(payload=b"<html>")))


def test_a_network_failure_is_a_provider_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(ProviderError, match="could not be reached"):
        create(RazorpayProvider("k", "s", client=client))


def test_a_reference_over_the_limit_never_leaves() -> None:
    rec = Recorder(payload=GOOD)
    with pytest.raises(ProviderError):
        create(provider(rec), reference_id="x" * 41)
    assert rec.requests == []


def test_cancel_calls_the_cancel_path_of_that_link_only() -> None:
    rec = Recorder(payload={"id": "plink_Abc123", "status": "cancelled"})
    provider(rec).cancel_link("plink_Abc123")
    [request] = rec.requests
    assert str(request.url) == f"{BASE_URL}/payment_links/plink_Abc123/cancel"


@pytest.mark.parametrize("link_id", ["", "../orders", "plink/1", "a b", "plink_1?x=1"])
def test_a_link_id_that_could_change_the_path_never_leaves(link_id: str) -> None:
    rec = Recorder(payload={})
    with pytest.raises(ProviderError):
        provider(rec).cancel_link(link_id)
    assert rec.requests == []


def test_only_the_fixed_host_is_ever_called() -> None:
    rec = Recorder(payload=GOOD)
    create(provider(rec))
    provider(rec).cancel_link("plink_1")
    assert {r.url.host for r in rec.requests} == {"api.razorpay.com"}
    assert {r.url.scheme for r in rec.requests} == {"https"}
