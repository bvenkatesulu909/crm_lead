"""Evaluation cases about the agent registry (ADR 0016): the case format and the scoring.

A case may say how the organisation set the agent up (``governance``) and whether the model must
have been called (``expect.model_called``). The database side is in the dataset tests.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.cases import Case
from agent_evals.runner import ScriptedModel, registry_outcome
from agent_evals.scoring import Trajectory, score_case
from app.modules.agents.service import AgentBudgetReachedError, AgentUnavailableError


def make(governance: dict[str, Any] | None = None, **expect: Any) -> Case:
    body: dict[str, Any] = {
        "id": "staff-governed-case",
        "description": "A governed case.",
        "agent": "staff_assistant",
        "as": "sales_agent",
        "messages": ["Show me my leads."],
        "expect": {"outcome": "agent_off", **expect},
    }
    if governance is not None:
        body["governance"] = governance
    return Case.model_validate(body)


def test_a_case_without_governance_has_none() -> None:
    assert make().governance is None


def test_governance_defaults_mean_on_standard_budget_all_tools() -> None:
    governance = make({}).governance
    assert governance is not None
    assert (governance.enabled, governance.monthly_token_budget) == (True, None)
    assert (governance.tokens_used, governance.allowed_tools) == (0, None)
    assert governance.platform_disabled is False


def test_governance_may_switch_cap_narrow_and_use_up() -> None:
    governance = make(
        {
            "enabled": False,
            "monthly_token_budget": 100,
            "tokens_used": 100,
            "allowed_tools": ["search_leads"],
            "platform_disabled": True,
        }
    ).governance
    assert governance is not None and governance.allowed_tools == ["search_leads"]


@pytest.mark.parametrize(
    "bad",
    [
        {"enabled": "maybe"},
        {"monthly_token_budget": 0},
        {"tokens_used": -1},
        {"unknown_field": 1},
        {"allowed_tools": ["delete_everything"]},
        {"allowed_tools": ["save_lead"]},  # a tool of another agent
    ],
)
def test_a_bad_governance_block_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make(bad)


def test_the_registry_outcome_words() -> None:
    assert registry_outcome(AgentUnavailableError()) == "agent_off"
    assert registry_outcome(AgentBudgetReachedError()) == "over_budget"


def test_the_two_new_outcomes_are_accepted() -> None:
    assert make(outcome="over_budget").expect.outcome == "over_budget"
    with pytest.raises(ValidationError):
        make(outcome="agent_exploded")


# --- "the model must not have been called" ---------------------------------------------------


def run(model_calls: int | None, outcome: str = "agent_off") -> Trajectory:
    return Trajectory(
        calls=[],
        answer="This assistant is not available.",
        outcome=outcome,
        model_calls=model_calls,
    )


def test_a_refused_agent_that_still_called_the_model_fails() -> None:
    result = score_case(make(model_called=False), run(model_calls=1))
    failed = [c for c in result.checks if not c.passed]
    assert [c.name for c in failed] == ["model_called"]
    assert "1 time" in failed[0].detail


def test_a_refused_agent_that_did_not_call_the_model_passes() -> None:
    assert score_case(make(model_called=False), run(model_calls=0)).passed


def test_an_answer_that_needed_the_model_fails_if_it_was_never_called() -> None:
    result = score_case(make(model_called=True, outcome="answered"), run(0, outcome="answered"))
    assert not result.passed


def test_the_check_is_skipped_when_the_case_does_not_ask_or_the_run_did_not_count() -> None:
    assert score_case(make(), run(model_calls=5)).passed
    assert score_case(make(model_called=False), run(model_calls=None)).passed


def test_the_scripted_model_counts_how_often_it_was_asked() -> None:
    model = ScriptedModel([])
    assert model.asked == 0
    model.reply(system="", messages=[], tools=[])
    model.reply(system="", messages=[], tools=[])
    assert model.asked == 2
