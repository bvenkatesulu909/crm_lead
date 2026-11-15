"""The company fields of a lead - pure rules (BP-02, ADR 0026 step EN1)."""

import typing

import pytest

from app.modules.leads.company import INDUSTRIES, SIZES, industry_label, normalise_website
from app.modules.leads.schemas import CompanyIndustry, CompanySize


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("example.com", "https://example.com"),
        ("Example.COM", "https://example.com"),
        ("https://www.example.co.in/", "https://www.example.co.in"),
        ("http://example.com", "https://example.com"),
        ("  example.com  ", "https://example.com"),
        ("example.com.", "https://example.com"),
        ("bücher.example", "https://xn--bcher-kva.example"),
        ("my-company.in", "https://my-company.in"),
    ],
)
def test_a_typed_website_becomes_https_and_the_host(typed: str, stored: str) -> None:
    assert normalise_website(typed) == stored


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "example",  # no dot
        "https://example.com/about",  # a page, not the site
        "example.com/?ref=crm",
        "example.com#top",
        "https://example.com:8443",  # a port
        "https://user:pass@example.com",
        "user@example.com",  # an e-mail address
        "ftp://example.com",
        "javascript:alert(1)",
        "http://127.0.0.1",
        "http://10.0.0.5",
        "http://[::1]",
        "https://-bad-.com",
        "https://exa mple.com",
        "https://" + "a" * 250 + ".com",  # too long
    ],
)
def test_anything_but_a_plain_website_is_refused(typed: str) -> None:
    with pytest.raises(ValueError):
        normalise_website(typed)


def test_the_schema_choices_are_the_same_as_the_rules() -> None:
    # The API's lists and the database's lists come from different places; they must agree.
    assert set(typing.get_args(CompanyIndustry)) == set(INDUSTRIES)
    assert typing.get_args(CompanySize) == SIZES


def test_an_industry_has_a_label_for_the_account() -> None:
    assert industry_label("real_estate") == "Real estate"
    assert industry_label(None) is None
    assert industry_label("castle") is None
    assert all(len(label) <= 100 for label in INDUSTRIES.values())  # account.industry is 100
