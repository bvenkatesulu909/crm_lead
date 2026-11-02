"""Estimated monthly cost of an AI agent (CRM-111, step LM2): the pure arithmetic.

Money is a ``Decimal`` and never a float (CLAUDE.md). The estimate is the month's input and output
tokens times the two prices per million tokens from the environment; it is not a bill. It is
``None`` when the agent uses no model or when no price is set, so a screen can say nothing about
money instead of a wrong "$0".
"""

from decimal import Decimal

import pytest

from app.modules.agents.cost import estimate_cost_usd


def cost(
    input_tokens: int = 0,
    output_tokens: int = 0,
    input_price: float = 3.0,
    output_price: float = 15.0,
    *,
    uses_model: bool = True,
) -> Decimal | None:
    return estimate_cost_usd(
        input_tokens,
        output_tokens,
        input_price_per_million=input_price,
        output_price_per_million=output_price,
        uses_model=uses_model,
    )


def test_it_is_the_tokens_times_the_two_prices() -> None:
    # 2 million in at 3 dollars + 1 million out at 15 dollars
    assert cost(2_000_000, 1_000_000) == Decimal("21.0000")


def test_input_and_output_are_priced_separately() -> None:
    assert cost(1_000_000, 0) == Decimal("3.0000")
    assert cost(0, 1_000_000) == Decimal("15.0000")


def test_no_usage_is_zero_dollars_when_a_price_is_set() -> None:
    assert cost(0, 0) == Decimal("0.0000")


def test_it_is_a_decimal_with_four_places_never_a_float() -> None:
    value = cost(123, 45)
    assert isinstance(value, Decimal)
    assert value == value.quantize(Decimal("0.0001"))


def test_a_price_that_floats_cannot_represent_is_exact() -> None:
    # 0.1 + 0.2 style drift must not appear: 3 million tokens at 0.1 is exactly 0.3.
    assert cost(3_000_000, 0, input_price=0.1, output_price=0.0) == Decimal("0.3000")


def test_it_rounds_half_up_to_four_places() -> None:
    # 5 tokens at 3.0 per million = 0.000015 -> 0.0000; 25 tokens = 0.000075 -> 0.0001
    assert cost(5, 0) == Decimal("0.0000")
    assert cost(25, 0) == Decimal("0.0001")


def test_without_any_price_the_answer_is_nothing_not_zero() -> None:
    assert cost(1_000_000, 1_000_000, input_price=0.0, output_price=0.0) is None


def test_one_price_is_enough() -> None:
    assert cost(1_000_000, 1_000_000, input_price=0.0, output_price=15.0) == Decimal("15.0000")


def test_an_agent_without_a_model_has_no_cost() -> None:
    assert cost(1_000_000, 1_000_000, uses_model=False) is None


@pytest.mark.parametrize("bad", [-1, -1_000_000])
def test_negative_tokens_are_refused(bad: int) -> None:
    with pytest.raises(ValueError):
        cost(bad, 0)
    with pytest.raises(ValueError):
        cost(0, bad)
