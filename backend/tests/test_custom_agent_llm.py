"""The scripted stand-in for the model of custom agents (CRM_AI_PROVIDER=fake).

It only ever uses the one tool it is offered, picks the first thing the agent may suggest, and its
answer passes the strict check of a run."""

from typing import Any

from app.core.config import Settings
from app.modules.custom_agents import run_rules
from app.modules.custom_agents.llm import FakeCustomAgentModel, model_for
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL


def ask(kinds: list[str]) -> Any:
    reply = FakeCustomAgentModel().reply(
        system="", messages=[], tools=[run_rules.submit_tool(kinds)]
    )
    return reply


def test_it_suggests_a_task_when_the_agent_may() -> None:
    kinds = ["lead.set_status", "activity.create_task"]
    reply = ask(kinds)
    assert [use.name for use in reply.tool_uses] == ["submit_suggestion"]
    suggestion = run_rules.parse_suggestion(reply.tool_uses[0].input, kinds)
    assert suggestion.action == "create_task" and suggestion.task_subject


def test_it_changes_a_status_when_only_that_is_allowed() -> None:
    kinds = ["lead.set_status"]
    suggestion = run_rules.parse_suggestion(ask(kinds).tool_uses[0].input, kinds)
    assert (suggestion.action, suggestion.status) == ("set_status", "contacted")


def test_it_suggests_nothing_when_nothing_is_allowed_or_offered() -> None:
    assert ask([]).tool_uses[0].input["action"] == "none"
    reply = FakeCustomAgentModel().reply(system="", messages=[], tools=[])
    assert reply.tool_uses == []


def test_the_fake_provider_selects_it_and_reports_tokens() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        ai_provider="fake",
    )
    assert isinstance(model_for(settings), FakeCustomAgentModel)
    assert ask(["activity.create_task"]).usage["input_tokens"] > 0
