"""Money is never a float (BP-20, docs/ci-security-gate.md, step SG1).

The first test is the gate: the API, the worker and the migrations keep no money as a float. The
others prove the checker can fail - each plants one mistake it must catch - and that ordinary
floats (ratings, ratios, seconds) are left alone, so the gate does not cry wolf.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from scripts.check_money_types import check_paths, check_source, looks_like_money, main

BACKEND = Path(__file__).resolve().parents[1]


def test_the_code_keeps_no_money_as_a_float() -> None:
    findings = check_paths([BACKEND / "app", BACKEND / "alembic"])
    assert findings == [], "\n".join(str(f) for f in findings)


@pytest.mark.parametrize(
    ("source", "what"),
    [
        ("price: float = 0.0\n", "'price'"),
        ("class S:\n    ai_input_price_per_million: float = 0.0\n", "ai_input_price_per_million"),
        ("total_inr: float | None = None\n", "'total_inr'"),
        ("amount: Mapped[float] = mapped_column()\n", "'amount'"),
        ("discount_amount: Optional[float]\n", "'discount_amount'"),
        ("def f(unit_price: float) -> None: ...\n", "parameter 'unit_price'"),
        ("def line_cost() -> float: ...\n", "'line_cost' looks like money but returns"),
        ("x = float(order.total_inr)\n", "float(total_inr)"),
        ("x = float(row['amount'])\n", "float(amount)"),
        ("col = sa.Column(sa.Float())\n", "Float column"),
        ("col = mapped_column(Double)\n", "Double column"),
        ("col = sa.Column(sa.Float)\n", "Float column"),
        ("budgetMax: float\n", "'budgetMax'"),
    ],
)
def test_a_planted_money_float_is_caught(source: str, what: str) -> None:
    findings = check_source(source, "planted.py")
    assert findings, f"not caught: {source!r}"
    assert any(what in f.what for f in findings), [f.what for f in findings]


@pytest.mark.parametrize(
    "source",
    [
        "average_rating: float | None = None\n",
        "conversion_rate: float\n",
        "timeout_seconds: float = 10\n",
        "total_seconds: float = 0.0\n",  # "total" alone is not money
        "similarity: float = 0.64\n",
        "x = float(avg)\n",
        "price: Decimal = Decimal(0)\n",
        "amount_inr: int = 0\n",
        "def f(share: float) -> int: ...\n",
        "price = 3.0\n",  # no annotation: nothing to judge (mypy keeps types honest)
    ],
)
def test_ordinary_floats_are_left_alone(source: str) -> None:
    assert check_source(source, "ok.py") == []


def test_an_exception_needs_a_marker_with_a_reason() -> None:
    with_reason = "c.inc(float(cost))  # money-float-ok: Prometheus counters only take float\n"
    without_reason = "c.inc(float(cost))  # money-float-ok:\n"
    elsewhere = "# money-float-ok: on another line\nc.inc(float(cost))\n"
    assert check_source(with_reason) == []
    assert check_source(without_reason) != []
    assert check_source(elsewhere) != []


def test_money_words_are_whole_words() -> None:
    assert looks_like_money("ai_output_price_per_million")
    assert looks_like_money("totalInr")
    assert looks_like_money("budget_min_inr")
    assert looks_like_money("subtotal")
    # parts of longer words are not money words
    assert not looks_like_money("priceless_flag")
    assert not looks_like_money("costume")
    assert not looks_like_money("total_count")


def test_the_command_fails_on_a_finding_and_passes_on_clean_code(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("price: float = 1.0\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text("price: Decimal\n", encoding="utf-8")
    assert main([str(bad)]) == 1
    assert main([str(good)]) == 0


def test_the_ai_prices_are_exact_decimals() -> None:
    # The reason for SG1: "0.28" from the environment stays exactly 0.28.
    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/none",
        "oidc_issuer": "http://localhost:9080/realms/crm",
    }
    settings = Settings(
        **base, ai_input_price_per_million="0.28", ai_output_price_per_million="0.42"
    )
    assert settings.ai_input_price_per_million == Decimal("0.28")
    assert isinstance(settings.ai_output_price_per_million, Decimal)
    with pytest.raises(ValueError):
        Settings(**base, ai_input_price_per_million="-1")
