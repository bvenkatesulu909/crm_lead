"""Price facts in the video brief (ADR 0041, step VB1b): pure rules, no database."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.video_brief import rules


def line(description: str = "3 BHK, Tower B", total: str = "12000000.00") -> rules.PriceLine:
    return rules.PriceLine(description, Decimal("1"), "unit", Decimal(total), Decimal(total))


def quote(currency: str = "INR", total: str = "12000000.00", **kw: object) -> rules.PriceFacts:
    base: dict[str, object] = dict(
        label="QT-0007", currency=currency, valid_until=date(2027, 1, 31),
        total=Decimal(total), lines=[line()],
    )  # fmt: skip
    base.update(kw)
    return rules.PriceFacts(**base)  # type: ignore[arg-type]


def make(**kw: object) -> rules.VideoBrief:
    base: dict[str, object] = dict(
        first_name="Suresh", language="en", goal="follow_up", tone="warm", length_seconds=60,
        facts=[], guesses=[], form_wishes=[],
    )  # fmt: skip
    base.update(kw)
    return rules.build_video_brief(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "currency", "text"),
    [
        ("12000000.00", "INR", "₹1,20,00,000"),
        ("12345678.50", "INR", "₹1,23,45,678.50"),
        ("999.00", "INR", "₹999"),
        ("1234567.00", "EUR", "EUR 1,234,567.00"),
    ],
)
def test_money_is_shown_as_stored_with_lakh_grouping_for_rupees(
    amount: str, currency: str, text: str
) -> None:
    assert rules.format_money(Decimal(amount), currency) == text


def test_a_quote_adds_cited_price_lines_and_the_total_to_the_script() -> None:
    brief = make(price=quote())
    price = [s for s in brief.script if s.kind == "price"]
    assert len(price) == 2  # one line and the total
    assert all(s.cites == ["QT-0007"] for s in price)
    assert "₹1,20,00,000" in price[0].text and "3 BHK, Tower B" in price[0].text
    assert "2027-01-31" in price[1].text
    known = [k for k in brief.known if k.kind == "price"]
    assert known and all(k.source == "QT-0007" for k in known)


def test_at_most_three_price_lines_reach_the_script() -> None:
    many = [line(f"Item {i}", str(10 + i)) for i in range(6)]
    brief = make(price=quote(lines=many))
    assert sum(1 for s in brief.script if s.kind == "price") == 3 + 1


def test_without_a_quote_no_price_is_ever_spoken() -> None:
    brief = make()
    assert not any(s.kind == "price" for s in brief.script)
    assert not any("₹" in s.text for s in brief.script)


def test_a_description_with_a_link_or_a_phone_number_is_cleaned_or_left_out() -> None:
    lines = [line("Flat see https://evil.example/x"), line("Call 98480 12345 for the flat")]
    brief = make(price=quote(lines=lines))
    spoken = " ".join(s.text for s in brief.script)
    assert "evil.example" not in spoken and "98480" not in spoken
    assert any(c.code == "value_left_out" for c in brief.cautions)


@pytest.mark.parametrize("language", ["en", "hi", "te"])
def test_price_lines_exist_in_every_language(language: str) -> None:
    brief = make(language=language, price=quote())
    assert [s for s in brief.script if s.kind == "price"]


def test_a_script_with_prices_too_long_for_the_length_is_reported() -> None:
    many = [line(f"A very long description of the flat number {i} in tower B") for i in range(3)]
    brief = make(length_seconds=30, price=quote(lines=many))
    assert any(c.code == "script_too_long" for c in brief.cautions)
