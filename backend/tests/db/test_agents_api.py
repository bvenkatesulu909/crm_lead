# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The agent registry API, audit, events and notifications (ADR 0016, step AG3).

Tenant admins read and change the settings, sales managers only read, everyone else is refused;
another organisation never sees or touches them. A switch flipped or a budget warning produces an
event that carries ids and codes only, and the admins hear about it (but not the one who did it).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.outbox import OutboxJob
from app.modules.agents import api as agents_api
from app.modules.agents.catalogue import AGENTS
from app.modules.agents.service import Limits
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_approvals_api import titles, worker  # noqa: F401 - fixture used by name
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world  # noqa: F401

URL = "/api/v1/agents"
KEY = "staff_assistant"
LIMITS = Limits(platform_disabled=False, default_monthly_tokens=1000)


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.admin"].tenant_id


def patch(api: Any, auth: Headers, who: str, key: str = KEY, **body: Any) -> Any:
    return api.patch(f"{URL}/{key}", json=body, headers=auth(who))


def events(db_session: Session, world: World, name: str) -> list[OutboxJob]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(OutboxJob).where(OutboxJob.kind == f"event.{name}")))


def use_tokens(db_session: Session, world: World, tokens: int, limits: Limits = LIMITS) -> Any:
    bind_principal(db_session, principal_for(world.users["alpha.admin"], ROLES["alpha.admin"]))
    result = agents_api.record_usage(
        db_session,
        alpha(world),
        KEY,
        input_tokens=tokens,
        output_tokens=0,
        limits=limits,
        now=datetime.now(UTC),
    )
    db_session.flush()  # what a request's commit does: the worker must be able to see the event
    return result


# --- who may read and change ------------------------------------------------------------------


def test_the_admin_sees_all_agents_with_their_settings_and_this_months_usage(
    api, auth, world
) -> None:
    body = ok(api.get(URL, headers=auth("alpha.admin")))
    assert [a["key"] for a in body["items"]] == list(AGENTS)
    staff = body["items"][0]
    assert staff["enabled"] is True and staff["budget_is_default"] is True
    assert staff["monthly_token_budget"] == 2_000_000  # the standard default
    assert staff["allowed_tools"] == staff["all_tools"] and len(staff["all_tools"]) == 9
    assert (staff["used_tokens"], staff["calls"], staff["percent_used"]) == (0, 0, 0)
    assert staff["version"] is None and staff["owner_role"] == "tenant_admin"


def test_a_sales_manager_may_read_but_not_change(api, auth, world) -> None:
    assert ok(api.get(f"{URL}/{KEY}", headers=auth("alpha.manager")))["key"] == KEY
    assert code_of(patch(api, auth, "alpha.manager", enabled=False))[0] == 403


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support", "alpha.customer"])
def test_others_are_refused(api, auth, world, who: str) -> None:
    assert api.get(URL, headers=auth(who)).status_code == 403
    assert api.get(f"{URL}/{KEY}", headers=auth(who)).status_code == 403
    assert patch(api, auth, who, enabled=False).status_code == 403


def test_without_a_token_it_is_401(api, world) -> None:
    assert api.get(URL).status_code == 401
    assert api.patch(f"{URL}/{KEY}", json={"enabled": False}).status_code == 401


def test_an_unknown_agent_is_404(api, auth, world) -> None:
    assert code_of(api.get(f"{URL}/no_such_agent", headers=auth("alpha.admin"))) == (
        404,
        "agent_not_found",
    )
    assert patch(api, auth, "alpha.admin", key="no_such_agent", enabled=False).status_code == 404


# --- changing ---------------------------------------------------------------------------------


def test_the_admin_switches_an_agent_off_and_back_on(api, auth, world) -> None:
    off = ok(patch(api, auth, "alpha.admin", enabled=False))
    assert off["enabled"] is False and off["version"] == 1
    on = ok(patch(api, auth, "alpha.admin", enabled=True, version=1))
    assert on["enabled"] is True and on["version"] == 2
    assert ok(api.get(f"{URL}/{KEY}", headers=auth("alpha.manager")))["enabled"] is True


def test_budget_and_tools_can_be_set_and_reset(api, auth, world) -> None:
    body = ok(
        patch(
            api,
            auth,
            "alpha.admin",
            monthly_token_budget=500_000,
            allowed_tools=["search_leads", "get_account"],
        )
    )
    assert body["monthly_token_budget"] == 500_000 and body["budget_is_default"] is False
    assert body["allowed_tools"] == ["get_account", "search_leads"]
    reset = ok(
        patch(api, auth, "alpha.admin", monthly_token_budget=None, allowed_tools=None, version=1)
    )
    assert reset["budget_is_default"] is True and reset["allowed_tools"] == reset["all_tools"]


def test_a_field_left_out_is_not_changed(api, auth, world) -> None:
    ok(patch(api, auth, "alpha.admin", monthly_token_budget=777))
    after = ok(patch(api, auth, "alpha.admin", enabled=False, version=1))
    assert after["monthly_token_budget"] == 777


def test_an_empty_change_is_refused(api, auth, world) -> None:
    assert patch(api, auth, "alpha.admin").status_code == 422


def test_a_stale_or_missing_version_is_a_conflict(api, auth, world) -> None:
    ok(patch(api, auth, "alpha.admin", enabled=False))
    assert code_of(patch(api, auth, "alpha.admin", enabled=True, version=9)) == (
        409,
        "version_conflict",
    )
    assert code_of(patch(api, auth, "alpha.admin", enabled=True))[0] == 409


@pytest.mark.parametrize(
    "body",
    [
        {"monthly_token_budget": 0},
        {"monthly_token_budget": -5},
        {"monthly_token_budget": 10_000_000_001},
        {"allowed_tools": ["delete_everything"]},
        {"allowed_tools": ["save_lead"]},  # a tool of another agent
        {"enabled": "perhaps"},
        {"tenant_id": str(uuid.uuid4()), "enabled": False},  # never taken from the client
        {"agent_key": "public_chat", "enabled": False},
    ],
)
def test_bad_input_is_refused(api, auth, world, body: dict[str, Any]) -> None:
    assert patch(api, auth, "alpha.admin", **body).status_code == 422


def test_another_organisation_has_its_own_settings(api, auth, world) -> None:
    ok(patch(api, auth, "alpha.admin", enabled=False, monthly_token_budget=5))
    beta = ok(api.get(f"{URL}/{KEY}", headers=auth("beta.admin")))
    assert beta["enabled"] is True and beta["budget_is_default"] is True and beta["version"] is None
    own = ok(patch(api, auth, "beta.admin", enabled=False))
    assert own["version"] == 1  # beta's own row, not alpha's
    assert ok(api.get(f"{URL}/{KEY}", headers=auth("alpha.admin")))["monthly_token_budget"] == 5


def test_usage_shows_in_the_read(api, auth, world, db_session) -> None:
    use_tokens(db_session, world, 250)
    staff = ok(api.get(f"{URL}/{KEY}", headers=auth("alpha.admin")))
    assert staff["used_tokens"] == 250 and staff["calls"] == 1
    assert staff["percent_used"] == 0  # 250 of 2,000,000
    ok(patch(api, auth, "alpha.admin", monthly_token_budget=1000))
    assert ok(api.get(f"{URL}/{KEY}", headers=auth("alpha.admin")))["percent_used"] == 25


# --- audit ------------------------------------------------------------------------------------


def test_every_change_through_the_api_is_audited(api, auth, world, db_session) -> None:
    ok(patch(api, auth, "alpha.admin", enabled=False))
    bind_tenant(db_session, alpha(world))
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "agent.updated"))
    assert row.actor_user_id == world.users["alpha.admin"].id and row.changes["agent"] == KEY
    assert row.changes["enabled"] == [True, False]


def test_reading_is_not_audited(api, auth, world, db_session) -> None:
    ok(api.get(URL, headers=auth("alpha.admin")))
    bind_tenant(db_session, alpha(world))
    assert (
        db_session.scalars(select(AuditLog).where(AuditLog.action == "agent.updated")).all() == []
    )


# --- events -----------------------------------------------------------------------------------


def test_flipping_the_switch_publishes_an_event_with_ids_and_codes_only(
    api, auth, world, db_session
) -> None:
    ok(patch(api, auth, "alpha.admin", enabled=False))
    [event] = events(db_session, world, "agent.switched")
    assert event.payload["data"] == {
        "agent": KEY,
        "state": "off",
        "actor_id": str(world.users["alpha.admin"].id),
    }
    ok(patch(api, auth, "alpha.admin", enabled=True, version=1))
    assert [e.payload["data"]["state"] for e in events(db_session, world, "agent.switched")] == [
        "off",
        "on",
    ]


def test_changing_only_the_budget_or_tools_publishes_no_switch_event(
    api, auth, world, db_session
) -> None:
    ok(patch(api, auth, "alpha.admin", monthly_token_budget=10))
    ok(patch(api, auth, "alpha.admin", allowed_tools=[], version=1))
    ok(patch(api, auth, "alpha.admin", enabled=True, version=2))  # already on: no change
    assert events(db_session, world, "agent.switched") == []


def test_the_budget_warning_event_is_published_once_per_month(world, db_session) -> None:
    assert use_tokens(db_session, world, 700).crossed_warning is False
    assert events(db_session, world, "agent.budget_warning") == []
    assert use_tokens(db_session, world, 100).crossed_warning is True
    assert use_tokens(db_session, world, 100).crossed_warning is False
    [event] = events(db_session, world, "agent.budget_warning")
    assert event.payload["data"] == {"agent": KEY, "percent": 80}


# --- notifications ----------------------------------------------------------------------------


def test_the_other_admins_hear_about_a_switch_but_not_the_one_who_did_it(
    api, auth, world, worker
) -> None:
    ok(patch(api, auth, "alpha.admin", enabled=False))
    worker()
    assert titles(api, auth, "alpha.admin") == []  # the actor
    for other in ("alpha.manager", "alpha.agent1", "alpha.support", "beta.admin"):
        assert titles(api, auth, other) == [], other


def test_every_admin_but_the_actor_is_told(api, auth, world, worker, db_session) -> None:
    """The test world has one admin per organisation, so a second one is made from the manager
    by giving them the admin role in their last token."""
    from sqlalchemy import update

    from app.modules.identity.models import User

    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(User)
        .where(User.id == world.users["alpha.manager2"].id)
        .values(roles=["tenant_admin"])
    )
    db_session.flush()
    ok(patch(api, auth, "alpha.admin", enabled=False))
    worker()
    assert titles(api, auth, "alpha.manager2") == ["AI agent switched off: Staff assistant"]
    assert titles(api, auth, "alpha.admin") == []


def test_the_admins_hear_when_a_month_passes_80_percent(
    api, auth, world, worker, db_session
) -> None:
    ok(patch(api, auth, "alpha.admin", monthly_token_budget=1000))
    use_tokens(db_session, world, 850)
    worker()
    assert titles(api, auth, "alpha.admin") == [
        "AI agent near its monthly limit (80 %): Staff assistant"
    ]
    assert titles(api, auth, "alpha.agent1") == []
    use_tokens(db_session, world, 50)
    worker()
    assert len(titles(api, auth, "alpha.admin")) == 1  # told once


def test_the_new_notification_types_are_known_to_the_settings_page(api, auth, world) -> None:
    types = {
        p["type"]
        for p in ok(api.get("/api/v1/notifications/preferences", headers=auth("alpha.admin")))
    }
    assert {"agent.switched", "agent.budget_warning"} <= types
