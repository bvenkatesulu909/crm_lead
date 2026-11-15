"""LLM usage and cost per agent (CRM-111, step LM1): the pure part, no database.

The four AI metrics (calls, duration, tokens, estimated cost) carry an ``agent`` label. The agent
comes from a context variable that the agent registry's wrapper sets for the length of a model call;
a call nobody wrapped is labelled ``unknown``. The label must stay bounded and must never carry a
tenant, a person or any text (ADR 0016).
"""

import threading
from decimal import Decimal

import pytest

from app.core.observability.metrics import (
    AI_COST,
    AI_DURATION,
    AI_REQUESTS,
    AI_TOKENS,
    REGISTRY,
    ai_agent,
    metrics_payload,
    observe_ai_call,
)

MODEL = "lm1-test-model"


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def call(**changes: object) -> None:
    observe_ai_call(
        **{
            "provider": "anthropic",
            "model": MODEL,
            "outcome": "ok",
            "seconds": 0.2,
            "input_tokens": 1000,
            "output_tokens": 500,
            "input_price_per_million": Decimal("3"),
            "output_price_per_million": Decimal("15"),
            **changes,
        }  # type: ignore[arg-type]
    )


def test_a_call_nobody_wrapped_is_labelled_unknown() -> None:
    before = value(
        "crm_ai_requests_total",
        provider="anthropic",
        model=MODEL,
        outcome="ok",
        agent="unknown",
    )
    call()
    after = value(
        "crm_ai_requests_total",
        provider="anthropic",
        model=MODEL,
        outcome="ok",
        agent="unknown",
    )
    assert after == before + 1


def test_every_ai_metric_carries_the_agent_label() -> None:
    with ai_agent("qualifier"):
        call()
    base = {"provider": "anthropic", "model": MODEL, "agent": "qualifier"}
    assert value("crm_ai_requests_total", outcome="ok", **base) >= 1
    assert value("crm_ai_request_duration_seconds_count", **base) >= 1
    assert value("crm_ai_tokens_total", direction="input", **base) >= 1000
    assert value("crm_ai_tokens_total", direction="output", **base) >= 500
    assert value("crm_ai_estimated_cost_usd_total", **base) > 0


def test_agents_are_counted_apart() -> None:
    def tokens(agent: str) -> float:
        return value(
            "crm_ai_tokens_total",
            provider="anthropic",
            model=MODEL,
            direction="input",
            agent=agent,
        )

    staff, chat = tokens("staff_assistant"), tokens("public_chat")
    with ai_agent("staff_assistant"):
        call(input_tokens=300)
    with ai_agent("public_chat"):
        call(input_tokens=70)
    assert tokens("staff_assistant") == staff + 300
    assert tokens("public_chat") == chat + 70


def test_the_cost_is_worked_out_from_the_tokens_and_the_two_prices() -> None:
    def cost() -> float:
        return value(
            "crm_ai_estimated_cost_usd_total",
            provider="anthropic",
            model=MODEL,
            agent="portal_assistant",
        )

    before = cost()
    with ai_agent("portal_assistant"):
        call(input_tokens=2_000_000, output_tokens=1_000_000)  # 2 x 3.0 + 1 x 15.0
    assert cost() == pytest.approx(before + 21.0)


def test_a_failed_call_counts_for_its_agent() -> None:
    with ai_agent("knowledge_answers"):
        call(outcome="error", input_tokens=0, output_tokens=0)
    assert (
        value(
            "crm_ai_requests_total",
            provider="anthropic",
            model=MODEL,
            outcome="error",
            agent="knowledge_answers",
        )
        >= 1
    )


def test_the_agent_goes_back_to_unknown_afterwards_even_after_an_error() -> None:
    with pytest.raises(RuntimeError), ai_agent("qualifier"):
        raise RuntimeError("the model failed")
    before = value(
        "crm_ai_requests_total",
        provider="anthropic",
        model=MODEL,
        outcome="ok",
        agent="unknown",
    )
    call()
    assert (
        value(
            "crm_ai_requests_total",
            provider="anthropic",
            model=MODEL,
            outcome="ok",
            agent="unknown",
        )
        == before + 1
    )


def test_nested_use_restores_the_outer_agent() -> None:
    with ai_agent("staff_assistant"):
        with ai_agent("qualifier"):
            pass
        before = value(
            "crm_ai_requests_total",
            provider="anthropic",
            model=MODEL,
            outcome="ok",
            agent="staff_assistant",
        )
        call()
    assert (
        value(
            "crm_ai_requests_total",
            provider="anthropic",
            model=MODEL,
            outcome="ok",
            agent="staff_assistant",
        )
        == before + 1
    )


def test_another_thread_does_not_inherit_the_agent() -> None:
    # A request on one thread must never be counted for the agent of a request on another.
    seen: list[float] = []

    def other() -> None:
        before = value(
            "crm_ai_requests_total",
            provider="anthropic",
            model=MODEL,
            outcome="ok",
            agent="unknown",
        )
        call()
        seen.append(
            value(
                "crm_ai_requests_total",
                provider="anthropic",
                model=MODEL,
                outcome="ok",
                agent="unknown",
            )
            - before
        )

    with ai_agent("qualifier"):
        worker = threading.Thread(target=other)
        worker.start()
        worker.join()
    assert seen == [1.0]


@pytest.mark.parametrize(
    "bad",
    ["", "Qualifier", "a b", "x" * 40, "agent{evil}", "tenant-123-4567", "../etc", "a\nb"],
)
def test_a_badly_formed_agent_name_is_labelled_unknown(bad: str) -> None:
    # The label must stay bounded and tame whatever a caller passes.
    before = value(
        "crm_ai_requests_total",
        provider="anthropic",
        model=MODEL,
        outcome="ok",
        agent="unknown",
    )
    with ai_agent(bad):
        call()
    assert (
        value(
            "crm_ai_requests_total",
            provider="anthropic",
            model=MODEL,
            outcome="ok",
            agent="unknown",
        )
        == before + 1
    )
    assert bad == "" or f'agent="{bad}"' not in metrics_payload()[0].decode()


def test_the_labels_are_exactly_the_documented_ones() -> None:
    # No tenant, person, question or answer can sneak in through a new label.
    assert AI_REQUESTS._labelnames == ("provider", "model", "outcome", "agent")
    assert AI_DURATION._labelnames == ("provider", "model", "agent")
    assert AI_TOKENS._labelnames == ("provider", "model", "direction", "agent")
    assert AI_COST._labelnames == ("provider", "model", "agent")
