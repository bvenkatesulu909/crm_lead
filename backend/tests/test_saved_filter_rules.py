"""Pure rules of saved filters (ADR 0042, BR-pre): no database."""

import uuid

import pytest

from app.modules.saved_filters import rules


def test_a_normal_filter_is_kept_and_tidied() -> None:
    cleaned = rules.clean_params(
        "account", {"segment": "enterprise", "q": "  Banyan   Builders ", "country": "IN"}
    )
    assert cleaned == {"segment": "enterprise", "q": "Banyan Builders", "country": "IN"}


@pytest.mark.parametrize(
    "key", ["archived", "limit", "offset", "tenant_id", "sql", "parent_account_id"]
)
def test_parameters_that_widen_or_page_a_list_are_refused(key: str) -> None:
    with pytest.raises(rules.InvalidFilterError):
        rules.clean_params("account", {"segment": "enterprise", key: "1"})


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"segment": "huge"},
        {"status": "deleted"},
        {"country": "india"},
        {"owner_id": "not-an-id"},
        {"q": "x" * 101},
        {"q": "hidden​char"},
        {"q": 5},
        {"min_value": "1000"},  # needs its currency
        {"value_currency": "INR"},  # needs its amount
        {"min_value": "-1", "value_currency": "INR"},
        {"min_value": "abc", "value_currency": "INR"},
        {"min_value": "NaN", "value_currency": "INR"},
        {"min_value": "1", "value_currency": "inr"},
    ],
)
def test_bad_values_are_refused(params: dict[str, object]) -> None:
    with pytest.raises(rules.InvalidFilterError):
        rules.clean_params("account", params)


def test_an_amount_and_its_currency_go_together() -> None:
    cleaned = rules.clean_params("account", {"min_value": "50000.50", "value_currency": "INR"})
    assert cleaned == {"min_value": "50000.5", "value_currency": "INR"}


def test_an_owner_is_a_clean_id() -> None:
    someone = uuid.uuid4()
    assert rules.clean_params("account", {"owner_id": str(someone).upper()}) == {
        "owner_id": str(someone)
    }


def test_only_accounts_can_be_saved_for_now() -> None:
    with pytest.raises(rules.InvalidFilterError):
        rules.clean_params("lead", {"status": "active"})


def test_too_many_parameters_are_refused() -> None:
    many = {f"k{i}": "x" for i in range(rules.MAX_PARAMS + 1)}
    with pytest.raises(rules.InvalidFilterError):
        rules.clean_account_params(many)


@pytest.mark.parametrize(
    "name", ["", "   ", "x" * 81, "see https://evil.example", "www.evil.example", "<b>hi</b>", "a‮b"]
)
def test_bad_names_are_refused(name: str) -> None:
    with pytest.raises(rules.InvalidFilterError):
        rules.clean_name(name)


def test_a_name_is_tidied() -> None:
    assert rules.clean_name("  Hyderabad   renewals ") == "Hyderabad renewals"


def test_only_the_owner_or_the_organisation_sees_a_filter() -> None:
    owner, other = uuid.uuid4(), uuid.uuid4()
    assert rules.Visibility(owner, False).visible_to(owner)
    assert not rules.Visibility(owner, False).visible_to(other)
    assert rules.Visibility(owner, True).visible_to(other)
