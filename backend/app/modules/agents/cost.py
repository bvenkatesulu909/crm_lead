"""The estimated cost of an AI agent's month (CRM-111, step LM2). Pure arithmetic, no database.

An estimate, not a bill: the month's input and output tokens times the two prices per million
tokens that the environment sets (``CRM_AI_INPUT_PRICE_PER_MILLION`` and the output one). Money is
a ``Decimal`` and never a float. The prices come from the server's settings only; nothing a client
sends can reach this.
"""

from decimal import ROUND_HALF_UP, Decimal

_MILLION = Decimal(1_000_000)
_PLACES = Decimal("0.0001")  # a hundredth of a cent: small agents still show a real number


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    *,
    input_price_per_million: float,
    output_price_per_million: float,
    uses_model: bool,
) -> Decimal | None:
    """Dollars for these tokens, rounded half up to four places - or ``None`` when there is
    nothing honest to say: the agent uses no model, or no price has been set (so "$0" would be a
    wrong answer, not a cheap one)."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts cannot be negative")
    if not uses_model:
        return None
    # str() first: Decimal(0.1) would carry the float's error, Decimal("0.1") does not.
    price_in = Decimal(str(input_price_per_million))
    price_out = Decimal(str(output_price_per_million))
    if price_in == 0 and price_out == 0:
        return None
    total = (Decimal(input_tokens) * price_in + Decimal(output_tokens) * price_out) / _MILLION
    return total.quantize(_PLACES, rounding=ROUND_HALF_UP)
