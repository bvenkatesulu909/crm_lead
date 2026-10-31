# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The web check in the agent registry and the staff assistant's tool (ADR 0019, step WC3).

The web check is a fifth entry of the registry (ADR 0016) that uses NO model: an organisation can
switch it off, and the page counts checks instead of tokens. The assistant's ``check_rera`` tool
only queues a lookup for a record the person may read - it never sees a page.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.outbox import OutboxJob
from app.modules.agents import service as agents_service
from app.modules.agents.catalogue import AGENTS
from app.modules.assistant import staff_tools
from app.modules.webcheck import service as webcheck
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, add_lead, alpha, principal_for
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world  # noqa: F401

KEY = "web_check"
RERA = "DEMO/RERA/2026/001"
LIMITS = agents_service.Limits(platform_disabled=False, default_monthly_tokens=1000)


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"webcheck_demo": True}
    values.update(overrides)
    return Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        **values,
    )


def person(db_session: Session, world: World, name: str):
    principal = principal_for(world.users[name], ROLES[name])
    bind_principal(db_session, principal)
    return principal


def calls_this_month(db_session: Session, world: World) -> int:
    bind_tenant(db_session, alpha(world))
    return agents_service.effective(db_session, alpha(world), KEY, LIMITS, datetime.now(UTC)).calls


def switch(db_session: Session, world: World, enabled: bool) -> None:
    admin = person(db_session, world, "alpha.admin")
    now = datetime.now(UTC)
    version = agents_service.effective(db_session, alpha(world), KEY, LIMITS, now).version
    agents_service.update_settings(
        db_session, admin, KEY, limits=LIMITS, now=now, version=version, enabled=enabled
    )


def jobs(db_session: Session, world: World) -> list[OutboxJob]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(OutboxJob).where(OutboxJob.kind == webcheck.CHECK_JOB)))


def ask(db_session: Session, world: World, who: str, target: uuid.UUID, **values: Any):
    return webcheck.request_check(
        db_session,
        person(db_session, world, who),
        target_type=values.pop("target_type", "lead"),
        target_id=target,
        source_key=values.pop("source_key", "demo_rera"),
        query=values.pop("query", RERA),
        settings=values.pop("config", settings()),
    )


# --- the registry entry ---------------------------------------------------------------------


def test_the_web_check_is_in_the_registry_and_uses_no_model() -> None:
    agent = AGENTS[KEY]
    assert agent.uses_model is False and agent.tools == ()
    # The only other feature without a model of ours is the outside AI client (ADR 0020).
    assert all(other.uses_model for key, other in AGENTS.items() if key not in (KEY, "mcp_client"))


def test_the_registry_page_lists_it_and_says_it_uses_no_model(api, auth, world) -> None:
    items = {
        a["key"]: a for a in ok(api.get("/api/v1/agents", headers=auth("alpha.admin")))["items"]
    }
    assert items[KEY]["uses_model"] is False and items[KEY]["enabled"] is True
    assert items[KEY]["calls"] == 0
    assert items["staff_assistant"]["uses_model"] is True


def test_an_admin_can_switch_it_off_and_on(api, auth, world) -> None:
    off = api.patch(f"/api/v1/agents/{KEY}", json={"enabled": False}, headers=auth("alpha.admin"))
    assert ok(off)["enabled"] is False
    version = ok(off)["version"]
    on = api.patch(
        f"/api/v1/agents/{KEY}",
        json={"enabled": True, "version": version},
        headers=auth("alpha.admin"),
    )
    assert ok(on)["enabled"] is True


@pytest.mark.parametrize("body", [{"monthly_token_budget": 5000}, {"allowed_tools": []}])
def test_a_budget_or_a_tool_list_makes_no_sense_for_it(api, auth, world, body) -> None:
    response = api.patch(f"/api/v1/agents/{KEY}", json=body, headers=auth("alpha.admin"))
    assert code_of(response) == (422, "invalid_agent_setting")


def test_it_has_no_token_budget_to_reach(db_session, world) -> None:
    """A model agent stops when its tokens are used up; this one has none to use."""
    person(db_session, world, "alpha.admin")
    agents_service.record_usage(
        db_session, alpha(world), KEY, input_tokens=10**9, output_tokens=0,
        limits=LIMITS, now=datetime.now(UTC),
    )  # fmt: skip
    agents_service.check_can_call(db_session, alpha(world), KEY, LIMITS, datetime.now(UTC))


def test_the_platform_ai_switch_does_not_stop_it(db_session, world) -> None:
    """The AI kill switch is about language models; this agent has none."""
    person(db_session, world, "alpha.admin")
    ai_off = agents_service.Limits(platform_disabled=True, default_monthly_tokens=1000)
    agents_service.check_can_call(db_session, alpha(world), KEY, ai_off, datetime.now(UTC))


def test_a_model_agent_is_still_stopped_by_the_ai_switch(db_session, world) -> None:
    person(db_session, world, "alpha.admin")
    ai_off = agents_service.Limits(platform_disabled=True, default_monthly_tokens=1000)
    with pytest.raises(agents_service.AgentUnavailableError):
        agents_service.check_can_call(
            db_session, alpha(world), "staff_assistant", ai_off, datetime.now(UTC)
        )


# --- the registry in front of the web check -------------------------------------------------


def test_a_check_counts_once_in_the_month(db_session, world) -> None:
    lead = add_lead(db_session, world)
    assert calls_this_month(db_session, world) == 0
    ask(db_session, world, "alpha.agent1", lead.id)
    ask(db_session, world, "alpha.agent1", lead.id, query="DEMO/RERA/2026/002")
    assert calls_this_month(db_session, world) == 2


def test_a_refused_check_is_not_counted(db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(Exception):  # noqa: B017 - several kinds of refusal, none may count
        ask(db_session, world, "alpha.agent2", lead.id)  # not theirs
    with pytest.raises(Exception):  # noqa: B017
        ask(db_session, world, "alpha.agent1", lead.id, query="https://evil.example/x")
    assert calls_this_month(db_session, world) == 0 and jobs(db_session, world) == []


def test_an_organisation_that_switched_it_off_gets_no_checks(db_session, world) -> None:
    lead = add_lead(db_session, world)
    switch(db_session, world, False)
    with pytest.raises(webcheck.WebCheckDisabledError):
        ask(db_session, world, "alpha.agent1", lead.id)
    assert jobs(db_session, world) == [] and calls_this_month(db_session, world) == 0


def test_switching_it_back_on_lets_checks_through(db_session, world) -> None:
    lead = add_lead(db_session, world)
    switch(db_session, world, False)
    switch(db_session, world, True)
    ask(db_session, world, "alpha.agent1", lead.id)
    assert len(jobs(db_session, world)) == 1


def test_another_organisations_switch_does_not_matter(db_session, world) -> None:
    lead = add_lead(db_session, world)
    bind_principal(db_session, principal_for(world.users["beta.admin"], ROLES["beta.admin"]))
    agents_service.update_settings(
        db_session, principal_for(world.users["beta.admin"], ROLES["beta.admin"]), KEY,
        limits=LIMITS, now=datetime.now(UTC), enabled=False,
    )  # fmt: skip
    ask(db_session, world, "alpha.agent1", lead.id)
    assert len(jobs(db_session, world)) == 1


def test_it_never_sends_a_token_budget_warning(db_session, world) -> None:
    lead = add_lead(db_session, world)
    ask(db_session, world, "alpha.agent1", lead.id)
    bind_tenant(db_session, alpha(world))
    warnings = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "event.agent.budget_warning")
    ).all()
    assert warnings == []


# --- the assistant's tool -------------------------------------------------------------------


def run_tool(db_session: Session, world: World, who: str, raw: dict[str, Any], config=None):
    principal = person(db_session, world, who)
    budget = staff_tools.ProposalBudget(settings=config if config is not None else settings())
    return staff_tools.execute(db_session, principal, "check_rera", raw, budget)


def tool_args(lead_id: uuid.UUID, **values: Any) -> dict[str, Any]:
    base = {
        "record_type": "lead",
        "record_id": str(lead_id),
        "source_key": "demo_rera",
        "query": RERA,
    }
    return base | values


def test_the_tool_is_listed_and_the_catalogue_knows_it() -> None:
    assert "check_rera" in staff_tools.TOOLS
    assert "check_rera" in AGENTS["staff_assistant"].tools
    schema = staff_tools.TOOLS["check_rera"].definition()["input_schema"]
    assert set(schema["properties"]) == {"record_type", "record_id", "source_key", "query"}
    assert schema.get("additionalProperties") is False


def test_the_tool_queues_a_check_and_says_nothing_has_been_looked_up_yet(db_session, world) -> None:
    lead = add_lead(db_session, world)
    result = run_tool(db_session, world, "alpha.agent1", tool_args(lead.id))
    assert result.outcome == "ok" and result.link == f"/leads/{lead.id}"
    assert "queued" in result.content and "request_id" in result.content
    assert "Lakeview" not in result.content  # the model never sees a page
    [job] = jobs(db_session, world)
    assert job.payload["requested_by_user_id"] == str(world.users["alpha.agent1"].id)
    assert calls_this_month(db_session, world) == 1


def test_the_tool_asks_as_the_person_not_as_the_model(db_session, world) -> None:
    """Whatever arguments the model sends, the check is the signed-in person's."""
    lead = add_lead(db_session, world, "alpha.agent1")
    other = world.users["alpha.admin"].id
    result = run_tool(
        db_session, world, "alpha.agent1", tool_args(lead.id) | {"requested_by_user_id": str(other)}
    )
    assert result.outcome == "invalid"  # an extra argument is refused
    assert jobs(db_session, world) == []


def test_the_tool_cannot_check_a_record_the_person_may_not_read(db_session, world) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    result = run_tool(db_session, world, "alpha.agent2", tool_args(lead.id))
    assert result.outcome == "not_found" and jobs(db_session, world) == []


def test_the_tool_works_for_an_account_too(db_session, world) -> None:
    result = run_tool(
        db_session,
        world,
        "alpha.agent1",
        tool_args(
            world.ids["A1"],
            record_type="account",
            source_key="demo_company",
            query="Demo Builders Pvt Ltd",
        ),
    )
    assert result.outcome == "ok" and result.link == f"/accounts/{world.ids['A1']}"


@pytest.mark.parametrize(
    "values",
    [
        {"query": "https://evil.example/x"},
        {"query": ""},
        {"source_key": "../etc"},
        {"record_type": "contact"},
        {"record_id": "not-a-uuid"},
    ],
)
def test_the_tool_refuses_bad_arguments_without_repeating_them(db_session, world, values) -> None:
    lead = add_lead(db_session, world)
    result = run_tool(db_session, world, "alpha.agent1", tool_args(lead.id) | values)
    assert result.is_error and "evil.example" not in result.content
    assert jobs(db_session, world) == []


def test_the_tool_says_so_when_the_web_check_is_switched_off(db_session, world) -> None:
    lead = add_lead(db_session, world)
    switch(db_session, world, False)
    result = run_tool(db_session, world, "alpha.agent1", tool_args(lead.id))
    assert result.is_error and "switched off" in result.content
    assert jobs(db_session, world) == []


def test_the_tool_says_so_when_the_limit_is_reached(db_session, world) -> None:
    lead = add_lead(db_session, world)
    config = settings(webcheck_per_user_hour=1)
    run_tool(db_session, world, "alpha.agent1", tool_args(lead.id), config)
    result = run_tool(db_session, world, "alpha.agent1", tool_args(lead.id), config)
    assert result.is_error and "too many" in result.content.lower()
    assert len(jobs(db_session, world)) == 1


def test_the_tool_does_nothing_without_the_application_settings(db_session, world) -> None:
    lead = add_lead(db_session, world)
    principal = person(db_session, world, "alpha.agent1")
    result = staff_tools.execute(
        db_session, principal, "check_rera", tool_args(lead.id), staff_tools.ProposalBudget()
    )
    assert result.is_error and jobs(db_session, world) == []


def test_a_person_without_the_permission_gets_nothing_from_the_tool(db_session, world) -> None:
    """The staff assistant is for staff; a customer's principal is refused by the service."""
    lead = add_lead(db_session, world)
    result = run_tool(db_session, world, "alpha.customer", tool_args(lead.id))
    assert result.is_error and jobs(db_session, world) == []


def test_the_registry_can_take_the_tool_away(db_session, world) -> None:
    """An organisation that removes it from the staff assistant's tools: the model is not offered
    it, and a call to it is dropped (the existing rule, now covering this tool)."""
    from app.modules.agents.governed import GovernedModel

    class Model:
        available = True

        def __init__(self) -> None:
            self.offered: list[str] = []

        def reply(self, *, system: str, messages: list[Any], tools: list[Any]):
            from app.modules.assistant.api import ModelReply, ToolUse

            self.offered = [t["name"] for t in tools]
            return ModelReply(
                "", [ToolUse("t1", "check_rera", {})], usage={"input_tokens": 5, "output_tokens": 5}
            )

    person(db_session, world, "alpha.admin")
    agents_service.update_settings(
        db_session, person(db_session, world, "alpha.admin"), "staff_assistant", limits=LIMITS,
        now=datetime.now(UTC),
        allowed_tools=[t for t in AGENTS["staff_assistant"].tools if t != "check_rera"],
    )  # fmt: skip
    inner = Model()
    governed = GovernedModel(inner, db_session, alpha(world), "staff_assistant", LIMITS)
    reply = governed.reply(system="", messages=[], tools=staff_tools.definitions())
    assert "check_rera" not in inner.offered and "search_leads" in inner.offered
    assert reply.tool_uses == [] and governed.dropped_tools == ["check_rera"]


# --- through the real staff assistant ------------------------------------------------------


class ScriptedModel:
    """Says what the script says and remembers the instructions it was given."""

    available = True

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.systems: list[str] = []

    def reply(self, *, system: str, messages: list[Any], tools: list[Any]):
        self.systems.append(system)
        return self.replies.pop(0)


def ask_assistant(db_session: Session, world: World, model: ScriptedModel, config: Settings):
    from app.modules.assistant import staff_service

    principal = person(db_session, world, "alpha.agent1")
    return staff_service.answer(
        db_session,
        principal,
        model,
        question="Please look up the RERA number for my lead.",
        budget=staff_tools.ProposalBudget(settings=config),
        limits=LIMITS,
    )


def test_the_instructions_name_the_sources_that_are_switched_on(db_session, world) -> None:
    from app.modules.assistant.api import ModelReply

    model = ScriptedModel(ModelReply("Nothing to look up."))
    ask_assistant(db_session, world, model, settings())
    assert "demo_rera = Demo RERA registry (rera)" in model.systems[0]
    assert "demo_company = Demo company registry (company)" in model.systems[0]


def test_the_instructions_name_no_source_when_none_is_on(db_session, world) -> None:
    from app.modules.assistant.api import ModelReply

    model = ScriptedModel(ModelReply("Nothing to look up."))
    ask_assistant(db_session, world, model, settings(webcheck_demo=False))
    assert "Web check sources" not in model.systems[0]


def test_a_question_can_queue_a_lookup_and_changes_nothing_else(db_session, world) -> None:
    from app.modules.assistant.api import ModelReply, ToolUse
    from app.modules.leads.models import Lead

    lead = add_lead(db_session, world, "alpha.agent1")
    before = (lead.status, lead.owner_id, lead.last_name)
    model = ScriptedModel(
        ModelReply("", [ToolUse("t1", "check_rera", tool_args(lead.id))]),
        ModelReply("I queued the lookup. The result will appear on the lead."),
    )
    answer, _ticket, links, proposals = ask_assistant(db_session, world, model, settings())
    assert "queued" in answer and proposals == []
    assert len(jobs(db_session, world)) == 1 and f"/leads/{lead.id}" in links
    db_session.refresh(lead)
    assert (lead.status, lead.owner_id, lead.last_name) == before
    assert db_session.get(Lead, lead.id) is lead


def test_the_model_is_told_nothing_was_found_yet(db_session, world) -> None:
    """The tool result the model reads says the lookup is queued and never to state a result."""
    from app.modules.assistant.api import ModelReply, ToolUse

    lead = add_lead(db_session, world, "alpha.agent1")
    seen: list[Any] = []

    class Spy(ScriptedModel):
        def reply(self, *, system: str, messages: list[Any], tools: list[Any]):
            seen.append(messages)
            return super().reply(system=system, messages=messages, tools=tools)

    model = Spy(
        ModelReply("", [ToolUse("t1", "check_rera", tool_args(lead.id))]), ModelReply("Queued.")
    )
    ask_assistant(db_session, world, model, settings())
    result = str(seen[-1][-1]["content"])
    assert "Never state a result" in result and "Lakeview" not in result
