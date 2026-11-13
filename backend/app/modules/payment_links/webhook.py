"""Reading a Razorpay webhook body (ADR 0031). Pure: no database, no network.

Called only AFTER the signature was checked. Anything unexpected becomes ``None`` ("ignore it"),
never an exception: a verified event we cannot read must still be answered 200, or Razorpay
retries it for days. Only the few facts the worker needs are kept: no customer e-mail, phone or
payment instrument is ever copied out of the body.
"""

import json
from dataclasses import dataclass
from typing import Any

# The events we act on. Everything else Razorpay may send is acknowledged and dropped.
HANDLED_EVENTS = ("payment_link.paid", "payment_link.expired", "payment_link.cancelled")
_MAX_ID = 60


@dataclass(frozen=True)
class ParsedEvent:
    event_type: str
    link_id: str
    facts: dict[str, Any]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= _MAX_ID else None


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _entity(payload: object, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    outer = payload.get(key)
    inner = outer.get("entity") if isinstance(outer, dict) else None
    return inner if isinstance(inner, dict) else {}


def parse_event(raw_body: bytes) -> ParsedEvent | None:
    try:
        data = json.loads(raw_body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    event_type = data.get("event")
    if event_type not in HANDLED_EVENTS:
        return None
    payload = data.get("payload")
    link_id = _text(_entity(payload, "payment_link").get("id"))
    if link_id is None:
        return None
    payment = _entity(payload, "payment")
    facts: dict[str, Any] = {
        "payment_id": _text(payment.get("id")),
        "amount_paise": _whole(payment.get("amount")),
        "currency": _text(payment.get("currency")),
    }
    return ParsedEvent(str(event_type), link_id, facts)
