# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The four AI call sites are behind the registry gate (ADR 0016, step AG2), through the API.

Staff assistant, customer portal assistant and public website chat are called over HTTP; the
knowledge answer is called through its service with the evaluation harness's world. In every
case a spy model fails the test if it is reached when it must not be.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from agent_evals import play
from agent_evals.rag import HashingEmbedder
from agent_evals.rag_cases import load_rag_cases
from agent_evals.suite import RAG_FILE
from agent_evals.world import World as EvalWorld
from app.core.config import Settings
from app.core.db import bind_tenant
from app.main import create_app
from app.modules.agents import service
from app.modules.agents.service import AgentBudgetReachedError, AgentUnavailableError, Limits
from app.modules.approvals.models import AgentAction
from app.modules.assistant.llm import ModelReply, ToolUse
from app.modules.knowledge import answers
from app.modules.leads.models import Lead
from app.modules.public_chat.models import PublicChatSession
from app.modules.public_chat.rules import RESTING_REPLY
from tests.auth_helpers import TEST_ISSUER, TokenFactory
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import bind_principal, session_factory_for, setup_lead_context
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import Headers, World, auth, world  # noqa: F401

ASK = "/api/v1/assistant/ask"
PORTAL = "/api/v1/portal/assistant/messages"
CHAT = "/api/v1/public/chat"
CHAT_KEY = "test-public-chat-key-" + "x" * 24  # fictional, test only
LIMITS = Limits(platform_disabled=False, default_monthly_tokens=2_000_000)
NOW = datetime.now(UTC)
App = Callable[..., TestClient]


class Spy:
    """Replays replies and records every call; ``reached`` says whether the model was used."""

    available = True

    def __init__(self, *replies: ModelReply) -> None:
        self.replies = list(replies)
        self.calls: list[list[str]] = []

    @property
    def reached(self) -> bool:
        return bool(self.calls)

    def reply(self, *, system: str, messages: list[Any], tools: list[Any]) -> ModelReply:
        self.calls.append([t["name"] for t in tools])
        if self.replies:
            return self.replies.pop(0)
        return ModelReply("Hello.", usage={"input_tokens": 30, "output_tokens": 10})


@pytest.fixture
def make_api(db_connection: Connection, token_factory: TokenFactory) -> Iterator[App]:
    clients: list[TestClient] = []

    def build(model: Any, **overrides: Any) -> TestClient:
        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=UNREACHABLE_DATABASE_URL,
            oidc_issuer=TEST_ISSUER,
            public_chat_tenant_slug="alpha-quotes",
            public_chat_server_key=SecretStr(CHAT_KEY),
            public_chat_provider="fake",
            assistant_messages_per_hour=1000,
            public_chat_messages_per_ip_hour=1000,
            public_chat_sessions_per_ip_hour=1000,
            **overrides,
        )
        app = create_app(
            settings,
            token_verifier=token_factory.verifier(),
            chat_model=model,
            public_chat_model=model,
        )
        app.state.session_factory = session_factory_for(db_connection)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def admin(db_session: Session, world: World, tenant: str = "alpha") -> Any:
    user = world.users[f"{tenant}.admin"]
    principal = principal_for(user, ROLES[f"{tenant}.admin"])
    bind_principal(db_session, principal)
    return principal


def configure(db_session: Session, world: World, key: str, **changes: Any) -> None:
    service.update_settings(
        db_session, admin(db_session, world), key, limits=LIMITS, now=NOW, **changes
    )


def exhaust(db_session: Session, world: World, key: str) -> None:
    admin(db_session, world)
    service.record_usage(
        db_session,
        world.users["alpha.admin"].tenant_id,
        key,
        input_tokens=2_000_000,
        output_tokens=0,
        limits=LIMITS,
        now=NOW,
    )


def staff_ask(api: TestClient, auth: Headers, user: str = "alpha.agent1") -> Any:
    return api.post(ASK, json={"question": "Help me with my leads"}, headers=auth(user))


def portal_say(api: TestClient, auth: Headers) -> Any:
    return api.post(
        PORTAL, json={"text": "Which orders do I have?"}, headers=auth("alpha.customer")
    )


def visitor_say(api: TestClient, token: str | None = None) -> Any:
    body: dict[str, Any] = {"message": "Hi, I want to see a 3BHK in Kokapet"}
    if token:
        body["token"] = token
    return api.post(
        CHAT, json=body, headers={"X-Public-Chat-Key": CHAT_KEY, "X-Visitor-Ip": "203.0.113.9"}
    )


def problem_code(response: Any) -> str:
    return str(response.json().get("code"))


# --- the platform switch stops all four -------------------------------------------------------


def test_the_platform_switch_stops_the_staff_assistant(make_api, auth, world) -> None:
    spy = Spy()
    response = staff_ask(make_api(spy, ai_disabled=True), auth)
    assert response.status_code == 503 and problem_code(response) == "agent_unavailable"
    assert not spy.reached


def test_the_platform_switch_stops_the_portal_assistant(make_api, auth, world) -> None:
    spy = Spy()
    response = portal_say(make_api(spy, ai_disabled=True), auth)
    assert response.status_code == 503 and problem_code(response) == "agent_unavailable"
    assert not spy.reached


def test_the_platform_switch_makes_the_website_chat_rest(make_api, world, db_session) -> None:
    spy = Spy()
    response = visitor_say(make_api(spy, ai_disabled=True))
    assert response.status_code == 200
    assert response.json()["reply"] == RESTING_REPLY and response.json()["lead_saved"] is False
    assert not spy.reached


def test_the_platform_switch_stops_the_knowledge_answer(db_session, world) -> None:
    spy = Spy()
    assert_knowledge_refused(db_session, spy, ai_disabled=True)


# --- one organisation's setting ---------------------------------------------------------------


def test_an_agent_switched_off_by_the_admin_stops_only_that_agent(
    make_api, auth, world, db_session
) -> None:
    configure(db_session, world, "staff_assistant", enabled=False)
    spy = Spy()
    api = make_api(spy)
    off = staff_ask(api, auth)
    assert off.status_code == 503 and problem_code(off) == "agent_unavailable"
    assert not spy.reached
    assert portal_say(api, auth).status_code == 200  # the portal assistant is unaffected
    assert spy.reached


def test_another_organisation_keeps_working_when_alpha_switches_off(
    make_api, auth, world, db_session
) -> None:
    configure(db_session, world, "staff_assistant", enabled=False)
    spy = Spy()
    assert staff_ask(make_api(spy), auth, "beta.agent").status_code == 200
    assert spy.reached


def test_over_budget_is_refused_with_its_own_code(make_api, auth, world, db_session) -> None:
    exhaust(db_session, world, "staff_assistant")
    spy = Spy()
    response = staff_ask(make_api(spy), auth)
    assert response.status_code == 503 and problem_code(response) == "agent_budget_reached"
    assert not spy.reached


def test_the_portal_assistant_over_budget_is_refused(make_api, auth, world, db_session) -> None:
    exhaust(db_session, world, "portal_assistant")
    spy = Spy()
    response = portal_say(make_api(spy), auth)
    assert response.status_code == 503 and problem_code(response) == "agent_budget_reached"
    assert not spy.reached


def test_the_website_chat_over_budget_rests_and_saves_no_lead(make_api, world, db_session) -> None:
    exhaust(db_session, world, "public_chat")
    spy = Spy()
    response = visitor_say(make_api(spy))
    assert response.json()["reply"] == RESTING_REPLY and not spy.reached
    setup_lead_context(db_session, world.users["alpha.admin"].tenant_id, scope="all")
    assert db_session.scalars(select(Lead).where(Lead.source == "web")).all() == []


def test_a_conversation_that_is_switched_off_midway_stops_at_the_next_step(
    make_api, auth, world, db_session
) -> None:
    spy = Spy()
    api = make_api(spy)
    first = visitor_say(api)
    assert first.status_code == 200 and spy.reached
    calls_before = len(spy.calls)
    configure(db_session, world, "public_chat", enabled=False)
    second = visitor_say(api, first.json()["token"])
    assert second.json()["reply"] == RESTING_REPLY
    assert len(spy.calls) == calls_before
    stored = db_session.scalars(select(PublicChatSession)).all()
    assert len(stored) == 1  # the same conversation continued, no new one


# --- metering and tools -----------------------------------------------------------------------


def test_a_successful_answer_is_metered(make_api, auth, world, db_session) -> None:
    assert staff_ask(make_api(Spy()), auth).status_code == 200
    admin(db_session, world)
    state = service.effective(
        db_session, world.users["alpha.admin"].tenant_id, "staff_assistant", LIMITS, NOW
    )
    assert (state.input_tokens, state.output_tokens, state.calls) == (30, 10, 1)


def test_the_staff_assistant_is_offered_only_the_allowed_tools(
    make_api, auth, world, db_session
) -> None:
    configure(db_session, world, "staff_assistant", allowed_tools=["search_leads"])
    spy = Spy()
    assert staff_ask(make_api(spy), auth).status_code == 200
    assert spy.calls == [["search_leads"]]


def test_a_proposing_tool_the_admin_removed_cannot_be_used_even_if_the_model_calls_it(
    make_api, auth, world, db_session
) -> None:
    configure(db_session, world, "staff_assistant", allowed_tools=["search_leads"])
    setup_lead_context(db_session, world.users["alpha.admin"].tenant_id, scope="all")
    lead = Lead(
        tenant_id=world.users["alpha.admin"].tenant_id,
        first_name="Asha",
        last_name="Rao",
        owner_id=world.users["alpha.agent1"].id,
    )
    db_session.add(lead)
    db_session.flush()
    sneaky = ModelReply(
        "",
        [
            ToolUse(
                "t1",
                "propose_lead_status",
                {"lead_id": str(lead.id), "status": "contacted", "reason": "x"},
            )
        ],
        stop_reason="tool_use",
    )
    spy = Spy(sneaky, ModelReply("I could not do that."))
    response = staff_ask(make_api(spy), auth)
    assert response.status_code == 200 and response.json()["proposals"] == []
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    assert db_session.scalars(select(AgentAction)).all() == []


# --- knowledge answers ------------------------------------------------------------------------


def assert_knowledge_refused(db_session: Session, spy: Spy, **overrides: Any) -> None:
    eval_world = EvalWorld(
        db_session,
        Settings(
            _env_file=None,
            environment="test",
            database_url=UNREACHABLE_DATABASE_URL,
            oidc_issuer=TEST_ISSUER,
            **overrides,
        ),
        "alpha-quotes",
        "beta-quotes",
    )
    embedder = HashingEmbedder()
    play.ingest_corpus(db_session, eval_world, embedder)
    case = next(c for c in load_rag_cases(RAG_FILE) if c.expect.model_called)
    principal, granted = play._rag_principal(eval_world, case.persona)
    with pytest.raises((AgentUnavailableError, AgentBudgetReachedError)):
        answers.answer_question(
            db_session,
            principal,
            embedder,
            spy,
            question=case.question,
            settings=play.rag_settings(eval_world),
            account_ids=granted,
        )
    assert not spy.reached


def test_the_knowledge_answer_off_for_one_organisation_never_reaches_the_model(
    db_session, world
) -> None:
    configure(db_session, world, "knowledge_answers", enabled=False)
    assert_knowledge_refused(db_session, Spy())


def test_the_knowledge_answer_over_budget_never_reaches_the_model(db_session, world) -> None:
    exhaust(db_session, world, "knowledge_answers")
    assert_knowledge_refused(db_session, Spy())


def test_an_unanswerable_question_needs_no_model_and_is_not_blocked_by_the_gate(
    db_session, world
) -> None:
    """The honest refusal happens before the gate: off or not, no model is involved."""
    configure(db_session, world, "knowledge_answers", enabled=False)
    eval_world = EvalWorld(
        db_session,
        Settings(
            _env_file=None,
            environment="test",
            database_url=UNREACHABLE_DATABASE_URL,
            oidc_issuer=TEST_ISSUER,
        ),
        "alpha-quotes",
        "beta-quotes",
    )
    embedder = HashingEmbedder()
    play.ingest_corpus(db_session, eval_world, embedder)
    case = next(c for c in load_rag_cases(RAG_FILE) if c.expect.outcome == "not_found")
    principal, granted = play._rag_principal(eval_world, case.persona)
    spy = Spy()
    outcome = answers.answer_question(
        db_session,
        principal,
        embedder,
        spy,
        question=case.question,
        settings=play.rag_settings(eval_world),
        account_ids=granted,
    )
    assert outcome.model_used is False and not spy.reached
