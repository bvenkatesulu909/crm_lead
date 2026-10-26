# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""The governed model (ADR 0016, step AG2): one gate in front of every model call.

A spy model fails the test if it is called when it must not be: that is how "an agent that is
off or over budget never reaches the model" is proven.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.observability.metrics import REGISTRY
from app.modules.agents import service
from app.modules.agents.catalogue import AGENTS
from app.modules.agents.governed import GovernedModel, governed
from app.modules.agents.service import (
    AgentBudgetReachedError,
    AgentUnavailableError,
    Limits,
)
from app.modules.assistant.llm import ModelReply, ToolUse
from tests.db.test_agents import Ctx, ctx  # noqa: F401 - fixture used by name
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
LIMITS = Limits(platform_disabled=False, default_monthly_tokens=1000)
KEY = "staff_assistant"
TOOLS = [{"name": "search_leads"}, {"name": "get_account"}, {"name": "propose_lead_status"}]


class Spy:
    """Replays replies, remembers what it was offered, and counts its calls."""

    available = True

    def __init__(self, *replies: ModelReply) -> None:
        self.replies = list(replies)
        self.calls: list[list[str]] = []

    def reply(self, *, system: str, messages: list[Any], tools: list[Any]) -> ModelReply:
        self.calls.append([t["name"] for t in tools])
        return self.replies.pop(0) if self.replies else ModelReply("ok", usage={})


def answer(text: str = "hello", input_tokens: int = 10, output_tokens: int = 5) -> ModelReply:
    return ModelReply(text, usage={"input_tokens": input_tokens, "output_tokens": output_tokens})


def gate(ctx: Ctx, spy: Any, limits: Limits = LIMITS, key: str = KEY) -> GovernedModel:
    ctx.who("alpha.admin")
    return governed(spy, ctx.session, ctx.alpha, key, limits, clock=lambda: NOW)


def call(model: Any, tools: list[Any] | None = None) -> ModelReply:
    reply: ModelReply = model.reply(
        system="s", messages=[], tools=TOOLS if tools is None else tools
    )
    return reply


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --- passing through and metering -------------------------------------------------------------


def test_an_allowed_call_goes_through_and_is_metered(ctx: Ctx) -> None:
    spy = Spy(answer("hi", 40, 12))
    assert call(gate(ctx, spy)).text == "hi"
    state = service.effective(ctx.session, ctx.alpha, KEY, LIMITS, NOW)
    assert (state.input_tokens, state.output_tokens, state.calls) == (40, 12, 1)


def test_a_reply_without_usage_still_counts_the_call(ctx: Ctx) -> None:
    call(gate(ctx, Spy(ModelReply("no usage given"))))
    state = service.effective(ctx.session, ctx.alpha, KEY, LIMITS, NOW)
    assert (state.used_tokens, state.calls) == (0, 1)


def test_the_wrapper_is_as_available_as_the_model_it_wraps(ctx: Ctx) -> None:
    spy = Spy()
    wrapped = gate(ctx, spy)
    assert wrapped.available is True
    spy.available = False
    assert wrapped.available is False


def test_wrapping_twice_does_not_stack_gates(ctx: Ctx) -> None:
    once = gate(ctx, Spy())
    assert governed(once, ctx.session, ctx.alpha, KEY, LIMITS, clock=lambda: NOW) is once


def test_the_warning_flag_is_kept_for_the_notification_step(ctx: Ctx) -> None:
    ctx.update(monthly_token_budget=100)
    wrapped = gate(ctx, Spy(answer("a", 70, 0), answer("b", 15, 0)))
    call(wrapped)
    assert wrapped.warning_due is False
    call(wrapped)  # 85 of 100
    assert wrapped.warning_due is True


# --- the gate ---------------------------------------------------------------------------------


def test_an_agent_that_is_off_never_reaches_the_model(ctx: Ctx) -> None:
    ctx.update(enabled=False)
    spy = Spy()
    with pytest.raises(AgentUnavailableError):
        call(gate(ctx, spy))
    assert spy.calls == []


def test_an_agent_over_budget_never_reaches_the_model(ctx: Ctx) -> None:
    ctx.use(1000)
    spy = Spy()
    with pytest.raises(AgentBudgetReachedError):
        call(gate(ctx, spy))
    assert spy.calls == []


def test_the_platform_switch_stops_every_agent(ctx: Ctx) -> None:
    off = Limits(platform_disabled=True, default_monthly_tokens=1000)
    spy = Spy()
    for key in AGENTS:
        with pytest.raises(AgentUnavailableError):
            call(gate(ctx, spy, off, key))
    assert spy.calls == []


def test_switching_off_stops_a_conversation_at_its_next_model_call(ctx: Ctx) -> None:
    spy = Spy(answer(), answer())
    wrapped = gate(ctx, spy)
    call(wrapped)  # the first step of a conversation
    ctx.update(enabled=False)  # an admin switches the agent off meanwhile
    with pytest.raises(AgentUnavailableError):
        call(wrapped)
    assert len(spy.calls) == 1


def test_one_agent_being_off_does_not_stop_another(ctx: Ctx) -> None:
    ctx.update(enabled=False)
    spy = Spy()
    call(gate(ctx, spy, key="public_chat"), tools=[{"name": "save_lead"}])
    assert spy.calls == [["save_lead"]]


def test_another_organisations_settings_do_not_apply(ctx: Ctx) -> None:
    ctx.update(enabled=False)  # alpha switches its agent off
    ctx.who("beta.admin")
    spy = Spy()
    wrapped = governed(spy, ctx.session, ctx.beta, KEY, LIMITS, clock=lambda: NOW)
    call(wrapped)
    assert len(spy.calls) == 1


# --- tools ------------------------------------------------------------------------------------


def test_the_model_is_offered_only_the_allowed_tools(ctx: Ctx) -> None:
    ctx.update(allowed_tools=["search_leads"])
    spy = Spy()
    call(gate(ctx, spy))
    assert spy.calls == [["search_leads"]]


def test_no_allowed_tools_means_none_are_offered(ctx: Ctx) -> None:
    ctx.update(allowed_tools=[])
    spy = Spy()
    call(gate(ctx, spy))
    assert spy.calls == [[]]


def test_all_tools_are_offered_by_default(ctx: Ctx) -> None:
    spy = Spy()
    call(gate(ctx, spy))
    assert spy.calls == [["search_leads", "get_account", "propose_lead_status"]]


def test_a_tool_the_model_calls_without_being_allowed_is_dropped(ctx: Ctx) -> None:
    ctx.update(allowed_tools=["search_leads"])
    sneaky = ModelReply(
        "",
        [ToolUse("1", "search_leads", {}), ToolUse("2", "propose_lead_status", {"x": 1})],
        stop_reason="tool_use",
    )
    wrapped = gate(ctx, Spy(sneaky))
    reply = call(wrapped)
    assert [u.name for u in reply.tool_uses] == ["search_leads"]
    assert wrapped.dropped_tools == ["propose_lead_status"]


def test_when_every_call_is_dropped_the_reply_is_plain_text(ctx: Ctx) -> None:
    ctx.update(allowed_tools=[])
    only_bad = ModelReply(
        "trying", [ToolUse("1", "propose_lead_status", {})], stop_reason="tool_use"
    )
    reply = call(gate(ctx, Spy(only_bad)))
    assert reply.tool_uses == [] and reply.stop_reason == "end_turn" and reply.text == "trying"


def test_a_tool_the_agent_never_had_passes_through_to_the_features_own_refusal(ctx: Ctx) -> None:
    """An invented name is not the organisation's decision: the dispatcher refuses it and the
    model is told. Only a real tool that the organisation removed is dropped."""
    invented = ModelReply("", [ToolUse("1", "delete_everything", {})], stop_reason="tool_use")
    wrapped = gate(ctx, Spy(invented))
    assert [u.name for u in call(wrapped).tool_uses] == ["delete_everything"]
    assert wrapped.dropped_tools == []


def test_tools_offered_to_the_knowledge_agent_are_always_none(ctx: Ctx) -> None:
    spy = Spy()
    call(gate(ctx, spy, key="knowledge_answers"), tools=[])
    assert spy.calls == [[]]


# --- metrics (no organisation in any label) ---------------------------------------------------


def test_refusals_and_dropped_tools_are_counted_without_a_tenant_label(ctx: Ctx) -> None:
    before = sample("crm_ai_refusals_total", agent=KEY, reason="disabled")
    ctx.update(enabled=False)
    with pytest.raises(AgentUnavailableError):
        call(gate(ctx, Spy()))
    assert sample("crm_ai_refusals_total", agent=KEY, reason="disabled") == before + 1

    dropped_before = sample("crm_ai_dropped_tool_calls_total", agent=KEY)
    ctx.update(enabled=True, allowed_tools=[], version=1)
    bad = ModelReply("", [ToolUse("1", "search_leads", {})], stop_reason="tool_use")
    call(gate(ctx, Spy(bad)))
    assert sample("crm_ai_dropped_tool_calls_total", agent=KEY) == dropped_before + 1
    for family in REGISTRY.collect():
        if family.name.startswith(("crm_ai_refusals", "crm_ai_dropped")):
            assert all(
                "tenant" not in s.labels and "organisation" not in s.labels for s in family.samples
            )


def test_session_type_is_the_requests_session(ctx: Ctx, db_session: Session) -> None:
    assert ctx.session is db_session
