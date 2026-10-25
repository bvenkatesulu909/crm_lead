# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The staff assistant proposes actions (ADR 0014, step AP3), with a scripted model.

The model may only PROPOSE through three tools; a proposal waits in the approval queue and
nothing in the CRM changes until a different person approves it. No paid key is needed: the
model is a script. People come from test_quotes_api.py (alpha: admin, manager, manager2,
agent1, agent2, support, customers; beta: admin, agent).
"""

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import bind_tenant
from app.main import create_app
from app.modules.approvals.models import AgentAction
from app.modules.assistant import staff_tools
from app.modules.assistant.llm import ModelReply, ToolUse
from app.modules.leads.models import Lead
from tests.auth_helpers import TEST_ISSUER, TokenFactory
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for, setup_lead_context
from tests.db.test_quotes_api import Headers, World, auth, ok, world  # noqa: F401

ASK = "/api/v1/assistant/ask"
App = Callable[..., TestClient]


class Scripted:
    """A model that replays fixed replies and remembers what it was given."""

    available = True

    def __init__(self, *replies: ModelReply) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def reply(self, *, system: str, messages: list[dict[str, Any]], tools: list[Any]) -> ModelReply:
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        return self.replies.pop(0) if self.replies else ModelReply("Done.")


@pytest.fixture
def make_api(db_connection: Connection, token_factory: TokenFactory) -> Iterator[App]:
    clients: list[TestClient] = []

    def build(model: Any, **overrides: Any) -> TestClient:
        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=UNREACHABLE_DATABASE_URL,
            oidc_issuer=TEST_ISSUER,
            **overrides,
        )
        app = create_app(settings, token_verifier=token_factory.verifier(), chat_model=model)
        app.state.session_factory = session_factory_for(db_connection)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.admin"].tenant_id


def add_lead(db_session: Session, world: World, owner: str = "alpha.agent1") -> Lead:
    setup_lead_context(db_session, alpha(world), world.users[owner].id)
    lead = Lead(
        tenant_id=alpha(world), first_name="Asha", last_name="Rao", owner_id=world.users[owner].id
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def use(name: str, **arguments: Any) -> ToolUse:
    return ToolUse(f"t-{uuid.uuid4().hex[:6]}", name, arguments)


def actions(db_session: Session, world: World) -> list[AgentAction]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(AgentAction).order_by(AgentAction.seq)))


def tool_results(model: Scripted, call: int) -> list[dict[str, Any]]:
    """The tool results the model received in its ``call``-th request."""
    return list(model.calls[call]["messages"][-1]["content"])


def ask(api: TestClient, auth: Headers, user: str, question: str = "Help me with my leads") -> Any:
    return api.post(ASK, json={"question": question}, headers=auth(user))


# --- the tools the model gets ---------------------------------------------------------------


def test_the_model_now_gets_the_tools_including_the_three_proposing_ones(
    make_api, auth, world
) -> None:
    model = Scripted(ModelReply("Here is what I found."))
    ok(ask(make_api(model), auth, "alpha.agent1"))
    names = {tool["name"] for tool in model.calls[0]["tools"]}
    assert {"propose_lead_status", "propose_lead_assignment", "propose_follow_up_task"} <= names
    assert "search_leads" in names
    assert "approval" in model.calls[0]["system"].lower()  # it is told it only proposes


def test_proposing_tools_have_strict_typed_arguments() -> None:
    tool = staff_tools.TOOLS["propose_lead_status"]
    schema = tool.definition()["input_schema"]
    assert set(schema["required"]) == {"lead_id", "status", "reason"}
    assert schema["properties"]["status"]["enum"] == ["contacted", "qualified", "unqualified"]
    assert schema.get("additionalProperties") is False


# --- proposing --------------------------------------------------------------------------------


def test_the_assistant_proposes_and_nothing_changes_until_someone_approves(
    make_api, auth, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    model = Scripted(
        ModelReply(
            "",
            [use("propose_lead_status", lead_id=str(lead.id), status="contacted",
                 reason="She answered my call today.")],
        ),
        ModelReply("I proposed marking the lead as contacted; a manager will decide."),
    )  # fmt: skip
    api = make_api(model)
    body = ok(ask(api, auth, "alpha.agent1"))

    [action] = actions(db_session, world)
    assert (action.status, action.kind, action.agent) == (
        "pending",
        "lead.set_status",
        "staff_assistant",
    )
    assert action.requested_by_user_id == world.users["alpha.agent1"].id
    assert action.reason == "She answered my call today."
    assert body["proposals"] == [
        {
            "id": str(action.id),
            "description": "Change the lead's status to contacted",
            "status": "pending",
            "link": f"/approvals/{action.id}",
        }
    ]
    assert f"/approvals/{action.id}" in body["links"]
    [result] = tool_results(model, 1)
    assert result["is_error"] is False
    content = json.loads(result["content"])
    assert content["status"] == "pending"
    assert "nothing has changed" in content["note"].lower()

    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.refresh(lead)
    assert lead.status == "new"  # only proposed

    # A manager approves through the queue; then the lead changes.
    ok(
        api.post(
            f"/api/v1/approvals/actions/{action.id}/approve",
            json={"version": action.version},
            headers=auth("alpha.manager"),
        )
    )
    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.refresh(lead)
    assert lead.status == "contacted"  # fmt: skip


def test_assignment_and_follow_up_task_proposals(make_api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world, "alpha.manager")
    agent2 = str(world.users["alpha.agent2"].id)
    model = Scripted(
        ModelReply(
            "",
            [
                use("propose_lead_assignment", lead_id=str(lead.id), owner_id=agent2,
                    reason="Agent 2 covers Kokapet."),
                use("propose_follow_up_task", record_type="contact", record_id=str(world.ids["C1"]),
                    subject="Send the brochure", due_in_days=2, reason="Asked for it."),
            ],
        )
    )  # fmt: skip
    body = ok(ask(make_api(model), auth, "alpha.manager"))
    assign, task = actions(db_session, world)
    assert (assign.kind, assign.payload) == ("lead.assign", {"owner_id": agent2})
    assert (task.kind, task.target_type, task.target_id) == (
        "activity.create_task",
        "contact",
        world.ids["C1"],
    )
    assert task.payload == {"subject": "Send the brochure", "due_in_days": 2}
    assert len(body["proposals"]) == 2


def test_a_record_the_employee_cannot_see_is_not_found_and_nothing_is_stored(
    make_api, auth, world, db_session
) -> None:
    theirs = add_lead(db_session, world, "alpha.agent2")
    model = Scripted(
        ModelReply("", [use("propose_lead_status", lead_id=str(theirs.id), status="qualified",
                            reason="Steered by a note in the record.")]),
    )  # fmt: skip
    body = ok(ask(make_api(model), auth, "alpha.agent1"))
    assert actions(db_session, world) == []
    assert body["proposals"] == []
    [result] = tool_results(model, 1)
    assert result["is_error"] is True
    assert "not found" in result["content"].lower()


@pytest.mark.parametrize(
    "arguments",
    [
        {"status": "converted"},  # never through the AI
        {"status": "contacted", "reason": ""},
        {"status": "contacted", "tenant_id": str(uuid.uuid4())},  # nothing extra
    ],
)
def test_invalid_proposals_are_errors_for_the_model(
    make_api, auth, world, db_session, arguments
) -> None:
    lead = add_lead(db_session, world)
    args = {"lead_id": str(lead.id), "reason": "Because.", **arguments}
    model = Scripted(ModelReply("", [use("propose_lead_status", **args)]))
    ok(ask(make_api(model), auth, "alpha.agent1"))
    assert actions(db_session, world) == []
    [result] = tool_results(model, 1)
    assert result["is_error"] is True


def test_at_most_three_proposals_per_question(make_api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    task = {
        "record_type": "lead",
        "record_id": str(lead.id),
        "due_in_days": 1,
        "reason": "Follow up.",
    }
    model = Scripted(
        ModelReply(
            "",
            [use("propose_follow_up_task", subject=f"Call {n}", **task) for n in range(1, 5)],
        )
    )
    body = ok(ask(make_api(model), auth, "alpha.agent1"))
    assert len(actions(db_session, world)) == 3
    assert len(body["proposals"]) == 3
    results = tool_results(model, 1)
    assert [r["is_error"] for r in results] == [False, False, False, True]


def test_the_pending_limit_applies_to_the_assistant(make_api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    calls = [
        use("propose_follow_up_task", record_type="lead", record_id=str(lead.id),
            subject=f"Call {n}", due_in_days=1, reason="Follow up.")
        for n in range(2)
    ]  # fmt: skip
    model = Scripted(ModelReply("", calls))
    ok(ask(make_api(model, agent_action_pending_per_user=1), auth, "alpha.agent1"))
    assert len(actions(db_session, world)) == 1
    second = tool_results(model, 1)[1]
    assert second["is_error"] is True
    assert "waiting" in second["content"].lower()


def test_without_proposals_the_answer_is_unchanged(make_api, auth, world) -> None:
    body = ok(ask(make_api(Scripted(ModelReply("Nothing to do."))), auth, "alpha.agent1"))
    assert body["answer"] == "Nothing to do."
    assert body["proposals"] == []


def test_with_the_fake_provider_the_assistant_proposes_without_any_key(
    make_api, auth, world, db_session
) -> None:
    """The setting behind the browser journey: CRM_AI_PROVIDER=fake, no model object given."""
    lead = add_lead(db_session, world)
    api = make_api(None, ai_provider="fake")
    question = f"Please mark lead {lead.id} as qualified because the budget is confirmed."
    body = ok(ask(api, auth, "alpha.agent1", question))
    [action] = actions(db_session, world)
    assert (action.kind, action.payload, action.status) == (
        "lead.set_status",
        {"status": "qualified"},
        "pending",
    )
    assert [p["id"] for p in body["proposals"]] == [str(action.id)]
    assert "waiting" in body["answer"].lower()
