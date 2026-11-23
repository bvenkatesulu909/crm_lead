"""Pure tests of the "what is usual" helpers and the quote state (ADR 0037, DR2)."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.deal_risk.baseline import MIN_SAMPLES, typical_amount, typical_days
from app.modules.deal_risk.signals import quote_state
from app.modules.quotes.api import DealQuote

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


def quote(status: str, valid_until: date) -> DealQuote:
    return DealQuote(
        id=uuid.uuid4(),
        label="QT-1",
        status=status,
        currency="INR",
        total=Decimal("1"),
        max_discount_percent=Decimal("0"),
        approval_limit_percent=Decimal("10"),
        valid_until=valid_until,
    )


def test_usual_values_need_enough_won_deals() -> None:
    assert MIN_SAMPLES == 5
    assert typical_days(None) is None
    assert typical_days([10, 20, 30, 40]) is None
    assert typical_days([10, 20, 30, 40, 50]) == 30
    assert typical_amount([Decimal(1)] * 4) is None
    assert typical_amount([Decimal(i) for i in (1, 2, 3, 4, 100)]) == Decimal(3)


def test_the_newest_live_quote_decides() -> None:
    future, past = date(2026, 12, 31), date(2026, 11, 1)
    assert quote_state([], NOW) == "none"
    # Drafts and superseded quotes do not count as a quote in play.
    assert quote_state([quote("draft", future), quote("superseded", future)], NOW) == "none"
    assert quote_state([quote("declined", future)], NOW) == "declined"
    assert quote_state([quote("pending_approval", future)], NOW) == "approval_waiting"
    assert quote_state([quote("sent", past)], NOW) == "expired"
    assert quote_state([quote("sent", future)], NOW) == "ok"
    # An accepted quote is never "expired" just because its validity date has gone by.
    assert quote_state([quote("accepted", past)], NOW) == "ok"
    # Newest first: an older declined quote behind a fresh sent one does not matter.
    assert quote_state([quote("sent", future), quote("declined", future)], NOW) == "ok"
