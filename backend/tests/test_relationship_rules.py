"""Pure rules of Phase B2 (no database): duplicate matching keys and customer health."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.matching import company_key, domain_key, phone_key
from app.modules.relationships.health import Signals, assess

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Example Ltd", "example limited"),
        ("Example GmbH", "EXAMPLE"),
        ("Example, Inc.", "Example Incorporated"),
        ("  Acme   Widgets  Co ", "acme widgets"),
    ],
)
def test_company_names_match_without_legal_forms(a: str, b: str) -> None:
    assert company_key(a) == company_key(b)


def test_different_companies_do_not_match() -> None:
    assert company_key("Example Widgets") != company_key("Example Gadgets")
    assert company_key("Ltd") == ""  # nothing left to compare


@pytest.mark.parametrize(
    ("website", "domain"),
    [
        ("https://www.example.com/about", "example.com"),
        ("http://example.com:8080", "example.com"),
        ("EXAMPLE.com", "example.com"),
        ("shop.example.com?x=1", "shop.example.com"),
    ],
)
def test_domain_key(website: str, domain: str) -> None:
    assert domain_key(website) == domain


def test_phone_key_ignores_formatting_and_country_prefix() -> None:
    assert phone_key("+44 20 7946 0018") == phone_key("020 7946 0018")
    assert phone_key("12") == ""  # too short to mean anything


def test_health_of_a_quiet_but_otherwise_fine_customer() -> None:
    health = assess(Signals(last_interaction_at=None), NOW)
    assert (health.score, health.label, health.inactive) == (80, "healthy", True)
    assert [f.label for f in health.factors] == ["No recorded interaction yet"]


@pytest.mark.parametrize(
    ("days", "score", "label", "inactive"),
    [(1, 100, "healthy", False), (40, 90, "healthy", False), (100, 70, "watch", True),
     (200, 55, "watch", True)],
)  # fmt: skip
def test_health_follows_inactivity(days: int, score: int, label: str, inactive: bool) -> None:
    health = assess(Signals(last_interaction_at=NOW - timedelta(days=days)), NOW)
    assert (health.score, health.label, health.inactive, health.days_inactive) == (
        score,
        label,
        inactive,
        days,
    )


def test_health_adds_up_problems_and_never_goes_below_zero() -> None:
    health = assess(
        Signals(
            last_interaction_at=NOW - timedelta(days=200),
            overdue_invoices=5,
            sla_overdue_tickets=2,
            open_complaints=1,
            average_rating=2.0,
            lifecycle_stage="churned",
        ),
        NOW,
    )
    assert health.score == 0
    assert health.label == "at_risk"
    impacts = {f.label: f.impact for f in health.factors}
    assert impacts["5 overdue invoices"] == -30  # capped
    assert impacts["Marked as churned"] == -40


def test_good_signals_are_shown_too() -> None:
    health = assess(
        Signals(
            last_interaction_at=NOW - timedelta(days=50),
            won_deals_last_year=2,
            average_rating=4.8,
        ),
        NOW,
    )
    assert health.score == 100  # 100 - 10 + 5 + 5, capped at 100
    assert {f.impact for f in health.factors} == {-10, 5}
