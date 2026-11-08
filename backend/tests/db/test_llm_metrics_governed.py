# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""LLM usage and cost per agent (CRM-111, step LM1): the agent registry's wrapper sets the label.

A model that meters itself (as the Claude and DeepSeek models do) is wrapped for each agent; the
call must be counted under THAT agent, a failed call too, and nothing may stay behind afterwards.
"""

import re
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.observability.metrics import REGISTRY, metrics_payload, observe_ai_call
from app.modules.agents import api as agents_api
from app.modules.agents.catalogue import AGENTS
from app.modules.agents.governed import governed
from app.modules.agents.service import AgentUnavailableError, Limits
from app.modules.assistant.llm import ModelReply
from tests.db.test_agents import Ctx, ctx  # noqa: F401 - fixture used by name
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
LIMITS = Limits(platform_disabled=False, default_monthly_tokens=1_000_000)
MODEL = "lm1-governed-model"
MODEL_AGENTS = [key for key, agent in AGENTS.items() if agent.uses_model]


class Metered:
    """Counts its own calls the way a real provider model does, then answers."""

    available = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def reply(self, *, system: str, messages: list[Any], tools: list[Any]) -> ModelReply:
        self.calls += 1
        if self.fail:
            observe_ai_call(provider="deepseek", model=MODEL, outcome="error", seconds=0.1)
            raise RuntimeError("the provider failed")
        observe_ai_call(
            provider="deepseek",
            model=MODEL,
            outcome="ok",
            seconds=0.1,
            input_tokens=400,
            output_tokens=100,
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        return ModelReply("hello", usage={"input_tokens": 400, "output_tokens": 100})


def requests(agent: str, outcome: str = "ok") -> float:
    return (
        REGISTRY.get_sample_value(
            "crm_ai_requests_total",
            {"provider": "deepseek", "model": MODEL, "outcome": outcome, "agent": agent},
        )
        or 0.0
    )


def gate(ctx: Ctx, model: Metered, key: str) -> Any:
    principal = ctx.who("alpha.admin")
    if not AGENTS[key].default_enabled:
        # An agent that starts switched off (ADR 0022) must be switched on before it can be called.
        agents_api.update_settings(
            ctx.session, principal, key, limits=LIMITS, now=NOW, enabled=True
        )
    return governed(model, ctx.session, ctx.alpha, key, LIMITS, clock=lambda: NOW)


def test_the_catalogue_has_the_eight_model_agents() -> None:
    # The web check uses no model and the MCP client's model runs outside the CRM.
    assert set(MODEL_AGENTS) == {
        "staff_assistant",
        "portal_assistant",
        "public_chat",
        "knowledge_answers",
        "qualifier",
        "lead_agent",
        "deal_desk",
        "account_research",
    }


@pytest.mark.parametrize("key", MODEL_AGENTS)
def test_a_governed_call_is_counted_under_its_own_agent(ctx: Ctx, key: str) -> None:
    before = {other: requests(other) for other in MODEL_AGENTS}
    gate(ctx, Metered(), key).reply(system="s", messages=[], tools=[])
    for other in MODEL_AGENTS:
        expected = before[other] + (1 if other == key else 0)
        assert requests(other) == expected, f"{other} while calling {key}"


def test_tokens_and_cost_follow_the_agent(ctx: Ctx) -> None:
    labels = {"provider": "deepseek", "model": MODEL, "agent": "public_chat"}
    before_tokens = (
        REGISTRY.get_sample_value("crm_ai_tokens_total", {**labels, "direction": "input"}) or 0.0
    )
    before_cost = REGISTRY.get_sample_value("crm_ai_estimated_cost_usd_total", labels) or 0.0
    gate(ctx, Metered(), "public_chat").reply(system="s", messages=[], tools=[])
    after_tokens = REGISTRY.get_sample_value(
        "crm_ai_tokens_total", {**labels, "direction": "input"}
    )
    after_cost = REGISTRY.get_sample_value("crm_ai_estimated_cost_usd_total", labels)
    assert after_tokens == before_tokens + 400
    assert after_cost == pytest.approx(before_cost + (400 * 1.0 + 100 * 2.0) / 1_000_000)


def test_a_failing_provider_is_counted_for_the_agent_and_leaves_nothing_behind(ctx: Ctx) -> None:
    before = requests("qualifier", "error")
    with pytest.raises(RuntimeError):
        gate(ctx, Metered(fail=True), "qualifier").reply(system="s", messages=[], tools=[])
    assert requests("qualifier", "error") == before + 1
    # The next call that nobody wrapped is not blamed on the Qualifier.
    unknown = requests("unknown")
    observe_ai_call(provider="deepseek", model=MODEL, outcome="ok", seconds=0.1)
    assert requests("unknown") == unknown + 1


def test_a_refused_call_never_reaches_the_provider_so_nothing_is_counted(ctx: Ctx) -> None:
    switched_off = Limits(platform_disabled=True, default_monthly_tokens=1_000_000)
    ctx.who("alpha.admin")
    model = Metered()
    gate_ = governed(model, ctx.session, ctx.alpha, "staff_assistant", switched_off)
    before = requests("staff_assistant")
    with pytest.raises(AgentUnavailableError):
        gate_.reply(system="s", messages=[], tools=[])
    assert model.calls == 0 and requests("staff_assistant") == before


def test_no_label_carries_a_tenant_or_a_person(ctx: Ctx) -> None:
    gate(ctx, Metered(), "staff_assistant").reply(system="s", messages=[], tools=[])
    body = metrics_payload()[0].decode()
    ai_lines = [line for line in body.splitlines() if line.startswith("crm_ai_")]
    assert ai_lines
    allowed = {
        "provider",
        "model",
        "outcome",
        "direction",
        "agent",
        "reason",
        "rule",
        "severity",
        "le",
    }
    for line in ai_lines:
        names = set(re.findall(r'(\w+)="', line))
        assert names <= allowed, line
        assert str(ctx.alpha) not in line
