# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Proposals from the MCP client (ADR 0020, step MCP5a) through the real API.

An outside AI client may only SUGGEST: the proposal lands in the same approval queue, a different
person approves it, and only the verified ``crm-mcp`` client may create one.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.main import create_app
from app.modules.approvals.models import AgentAction
from app.modules.leads.models import Lead
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for, setup_lead_context
from tests.db.test_approvals_api import ACTIONS, add_lead, alpha, lead_status
from tests.db.test_quotes_api import PEOPLE, Headers, World, api, auth, ok, world  # noqa: F401

EXTERNAL = "/api/v1/approvals/proposals/external"
AGENT = "/api/v1/agents/mcp_client"
REASON = "The buyer confirmed their budget on the phone."


@pytest.fixture
def mcp(token_factory: TokenFactory, world: World) -> Headers:
    """Headers for a person signed in THROUGH the MCP client (the token's azp is crm-mcp)."""
    return lambda name: bearer(token_factory.mint(f"sub-{name}", [PEOPLE[name][1]], azp="crm-mcp"))


def client_with(
    db_connection: Connection, token_factory: TokenFactory, **settings: Any
) -> Iterator[TestClient]:
    config = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        **settings,
    )
    app = create_app(config, token_verifier=token_factory.verifier())
    app.state.session_factory = session_factory_for(db_connection)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def api_ai_off(db_connection: Connection, token_factory: TokenFactory) -> Iterator[TestClient]:
    yield from client_with(db_connection, token_factory, ai_disabled=True)


@pytest.fixture
def api_two_an_hour(db_connection: Connection, token_factory: TokenFactory) -> Iterator[TestClient]:
    yield from client_with(db_connection, token_factory, mcp_proposals_per_hour=2)


def switch_on(api: TestClient, auth: Headers, version: int | None = None) -> None:
    body: dict[str, Any] = {"enabled": True}
    if version is not None:
        body["version"] = version
    ok(api.patch(AGENT, json=body, headers=auth("alpha.admin")))


def body(lead: Lead, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "lead.set_status",
        "target_type": "lead",
        "target_id": str(lead.id),
        "payload": {"status": "contacted"},
        "reason": REASON,
    } | extra


def stored(db_session: Session, world: World) -> list[AgentAction]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(AgentAction)))


# --- who may create one ---------------------------------------------------------------------


def test_it_is_switched_off_until_an_administrator_turns_it_on(
    api, auth, mcp, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    ok(api.get(AGENT, headers=auth("alpha.admin")))  # visible in the registry...
    assert ok(api.get(AGENT, headers=auth("alpha.admin")))["enabled"] is False  # ...but off

    response = api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1"))
    assert (response.status_code, response.json()["code"]) == (503, "agent_unavailable")
    assert stored(db_session, world) == []


def test_after_the_switch_the_client_can_only_suggest(api, auth, mcp, world, db_session) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)

    made = ok(api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1")), 201)
    assert made["status"] == "pending"
    assert made["agent"] == "mcp_client" and made["via_client"] == "crm-mcp"
    assert made["requested_by_user_id"] == str(world.users["alpha.agent1"].id)
    assert lead_status(db_session, world, lead) == "new"  # nothing has changed
    (row,) = stored(db_session, world)
    assert (row.agent, row.via_client) == ("mcp_client", "crm-mcp")


def test_the_switch_belongs_to_one_organisation(api, auth, mcp, world, db_session) -> None:
    switch_on(api, auth)  # alpha only
    bind_tenant(db_session, world.users["beta.agent"].tenant_id)
    setup_lead_context(
        db_session, world.users["beta.agent"].tenant_id, world.users["beta.agent"].id
    )
    beta_lead = Lead(
        tenant_id=world.users["beta.agent"].tenant_id,
        last_name="Beta",
        owner_id=world.users["beta.agent"].id,
    )
    db_session.add(beta_lead)
    db_session.flush()

    response = api.post(EXTERNAL, json=body(beta_lead), headers=mcp("beta.agent"))
    assert (response.status_code, response.json()["code"]) == (503, "agent_unavailable")


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.manager", "alpha.admin"])
def test_only_the_mcp_client_may_use_the_endpoint(api, auth, mcp, world, db_session, who) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    switch_on(api, auth)

    response = api.post(EXTERNAL, json=body(lead), headers=auth(who))  # a crm-web token
    assert (response.status_code, response.json()["code"]) == (
        403,
        "external_client_not_allowed",
    )
    assert stored(db_session, world) == []


def test_a_token_without_a_client_name_is_refused_too(
    api, auth, token_factory, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    token = token_factory.sign(
        {
            k: v
            for k, v in token_factory.claims("sub-alpha.agent1", ["sales_agent"]).items()
            if k != "azp"
        }
    )
    response = api.post(EXTERNAL, json=body(lead), headers=bearer(token))
    assert (response.status_code, response.json()["code"]) == (403, "external_client_not_allowed")


def test_customers_and_anonymous_callers_are_refused(api, auth, mcp, world, db_session) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    assert api.post(EXTERNAL, json=body(lead)).status_code == 401
    assert api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.customer")).status_code == 403
    assert stored(db_session, world) == []


def test_the_platform_kill_switch_stops_it_too(
    api, api_ai_off, auth, mcp, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)  # the organisation allows it...
    response = api_ai_off.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1"))
    assert (response.status_code, response.json()["code"]) == (503, "agent_unavailable")
    assert stored(db_session, world) == []  # ...but the platform switch wins


def test_switching_it_off_again_stops_new_proposals(api, auth, mcp, world, db_session) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    version = ok(api.get(AGENT, headers=auth("alpha.admin")))["version"]
    ok(api.patch(AGENT, json={"enabled": False, "version": version}, headers=auth("alpha.admin")))
    assert api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1")).status_code == 503


# --- what may be proposed -------------------------------------------------------------------


def test_the_body_is_strict_and_the_server_decides_who_and_what(
    api, auth, mcp, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    for extra in (
        {"tenant_id": str(uuid.uuid4())},
        {"requested_by_user_id": str(world.users["alpha.manager"].id)},
        {"agent": "staff_assistant"},
        {"via_client": "crm-web"},
        {"status": "approved"},
    ):
        response = api.post(EXTERNAL, json=body(lead) | extra, headers=mcp("alpha.agent1"))
        assert response.status_code == 422, extra
    assert stored(db_session, world) == []


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "lead.delete"},
        {"kind": "lead.set_status", "payload": {"status": "converted"}},
        {"payload": {"status": "contacted", "owner_id": str(uuid.uuid4())}},
        {"reason": ""},
        {"reason": "x" * 501},
    ],
)
def test_only_the_known_kinds_with_strict_payloads(
    api, auth, mcp, world, db_session, change
) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    response = api.post(EXTERNAL, json=body(lead) | change, headers=mcp("alpha.agent1"))
    assert response.status_code == 422
    assert stored(db_session, world) == []


def test_the_record_must_be_one_the_person_may_see(api, auth, mcp, world, db_session) -> None:
    others_lead = add_lead(db_session, world, "alpha.agent2")
    switch_on(api, auth)

    # Another agent's lead, a made-up id and (see the isolation test) another organisation's:
    # all the same answer.
    made_up = others_lead.id.__class__(int=others_lead.id.int ^ 1)
    for target in (others_lead.id, made_up):
        response = api.post(
            EXTERNAL,
            json=body(others_lead) | {"target_id": str(target)},
            headers=mcp("alpha.agent1"),
        )
        assert (response.status_code, response.json()["code"]) == (404, "record_not_found")
    assert stored(db_session, world) == []


def test_a_link_in_the_reason_is_blocked_by_the_sentinel(api, auth, mcp, world, db_session) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    response = api.post(
        EXTERNAL,
        json=body(lead, reason="Per http://evil.example/notes the lead is ready"),
        headers=mcp("alpha.agent1"),
    )
    assert (response.status_code, response.json()["code"]) == (422, "proposal_blocked")
    assert stored(db_session, world) == []


def test_assignment_and_task_kinds_work_the_same_way(api, auth, mcp, world, db_session) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    switch_on(api, auth)
    task = body(lead) | {
        "kind": "activity.create_task",
        "payload": {"subject": "Call the buyer", "due_in_days": 2},
    }
    assert (
        ok(api.post(EXTERNAL, json=task, headers=mcp("alpha.agent1")), 201)["status"] == "pending"
    )
    assign = body(lead) | {
        "kind": "lead.assign",
        "payload": {"owner_id": str(world.users["alpha.agent2"].id)},
    }
    assert (
        ok(api.post(EXTERNAL, json=assign, headers=mcp("alpha.agent1")), 201)["status"] == "pending"
    )


# --- the ceiling for this source ------------------------------------------------------------


def test_this_source_has_its_own_hourly_ceiling(
    api_two_an_hour, api, auth, mcp, world, db_session
) -> None:
    leads = [add_lead(db_session, world, "alpha.agent1") for _ in range(3)]
    switch_on(api, auth)
    first, second, third = (
        api_two_an_hour.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1"))
        for lead in leads
    )
    assert (first.status_code, second.status_code) == (201, 201)
    assert (third.status_code, third.json()["code"]) == (429, "mcp_proposal_limit_reached")
    # It counts this person's proposals made through the client, not the colleague's.
    colleague_lead = add_lead(db_session, world, "alpha.agent2")
    assert (
        api_two_an_hour.post(
            EXTERNAL, json=body(colleague_lead), headers=mcp("alpha.agent2")
        ).status_code
        == 201
    )


# --- humans decide, in the CRM ---------------------------------------------------------------


def test_only_a_different_person_can_approve_and_only_then_the_lead_changes(
    api, auth, mcp, world, db_session
) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    switch_on(api, auth)
    made = ok(api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1")), 201)
    decide = f"{ACTIONS}/{made['id']}/approve"

    # The asker cannot approve it, not even with a crm-mcp token, and a manager's crm-mcp token
    # is not a way around the person: approving is a decision made in the CRM.
    assert api.post(decide, json={"version": 1}, headers=auth("alpha.agent1")).status_code == 403
    assert lead_status(db_session, world, lead) == "new"

    ok(api.post(decide, json={"version": 1}, headers=auth("alpha.manager")))
    assert lead_status(db_session, world, lead) == "contacted"
    card = ok(api.get(f"{ACTIONS}/{made['id']}", headers=auth("alpha.manager")))
    assert card["via_client"] == "crm-mcp" and card["status"] == "approved"


def test_the_audit_entry_names_the_client(api, auth, mcp, world, db_session) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    made = ok(api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1")), 201)
    bind_tenant(db_session, alpha(world))
    entry = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "agent_action.proposed", AuditLog.entity_id == uuid.UUID(made["id"])
        )
    ).one()
    assert entry.changes["via_client"] == "crm-mcp" and entry.changes["agent"] == "mcp_client"


def test_the_database_only_knows_the_listed_agents(db_session, world) -> None:
    from sqlalchemy.exc import IntegrityError

    bind_tenant(db_session, alpha(world))
    setup_lead_context(db_session, alpha(world), world.users["alpha.agent1"].id)
    lead = Lead(tenant_id=alpha(world), last_name="X", owner_id=world.users["alpha.agent1"].id)
    db_session.add(lead)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            AgentAction(
                tenant_id=alpha(world),
                kind="lead.set_status",
                target_type="lead",
                target_id=lead.id,
                payload={"status": "contacted"},
                reason="x",
                agent="some_other_client",
                requested_by_user_id=world.users["alpha.agent1"].id,
                expires_at=lead.created_at,
            )
        )
        db_session.flush()


def test_each_proposal_counts_as_one_call_on_the_registry_page(
    api, auth, mcp, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    assert ok(api.get(AGENT, headers=auth("alpha.admin")))["calls"] == 0
    ok(api.post(EXTERNAL, json=body(lead), headers=mcp("alpha.agent1")), 201)
    page = ok(api.get(AGENT, headers=auth("alpha.admin")))
    assert page["calls"] == 1 and page["used_tokens"] == 0  # no tokens of ours to count


def test_a_refused_proposal_leaves_an_audit_entry_but_no_proposal(
    api, auth, mcp, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    switch_on(api, auth)
    response = api.post(
        EXTERNAL,
        json=body(lead, reason="Per http://evil.example/notes the lead is ready"),
        headers=mcp("alpha.agent1"),
    )
    assert response.status_code == 422
    assert stored(db_session, world) == []
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "agent_action.blocked")
    ).one()
    assert entry.changes["agent"] == "mcp_client"
    assert "evil.example" not in str(entry.changes)  # rule codes and ids, never the text found
