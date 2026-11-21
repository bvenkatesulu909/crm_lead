# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Notifications about custom agents (ADR 0034).

The other administrators hear that one was switched on or off, and when one is near its monthly
limit - by the name the administrator gave it, also after it was retired - and the link goes to the
Custom agents page, not the page of the built-in agents."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.core.events import publish
from app.modules.agents import api as agents_api
from app.modules.identity.models import User
from tests.db.test_agents_api import LIMITS, alpha
from tests.db.test_approvals_api import worker  # noqa: F401 - fixture used by name
from tests.db.test_custom_agents_api import (
    URL,
    created,
    lead,
    says,
    switch_on,
    try_it,
    use,
)
from tests.db.test_quotes_api import Headers, World, api, auth, ok, world

AGENTS = "/api/v1/agents"
NAME = "Quiet lead helper"


def notifications(api: Any, auth: Headers, who: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = ok(api.get("/api/v1/notifications", headers=auth(who)))["items"]
    return items


def second_admin(db_session: Session, world: World) -> None:
    """The test world has one admin per organisation, so a second one is made from a manager."""
    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(User)
        .where(User.id == world.users["alpha.manager2"].id)
        .values(roles=["tenant_admin"])
    )
    db_session.flush()


def tried_agent(api: Any, auth: Headers, lead: Any) -> dict[str, Any]:
    agent = created(api, auth)
    use(api, says())
    ok(try_it(api, auth, agent, lead.id))
    return agent


def test_the_other_admins_hear_that_a_custom_agent_was_switched_on_and_by_what_name(
    api, auth, world, worker, db_session, lead
) -> None:
    agent = tried_agent(api, auth, lead)
    second_admin(db_session, world)
    ok(switch_on(api, auth, agent))
    worker()
    [note] = notifications(api, auth, "alpha.manager2")
    assert note["title"] == f"AI agent switched on: {NAME} (custom agent)"
    assert note["link"] == "/automation/custom-agents"
    # Not the one who did it, and nobody who does not manage agents or belongs elsewhere.
    for nobody in ("alpha.admin", "alpha.manager", "alpha.agent1", "alpha.support", "beta.admin"):
        assert notifications(api, auth, nobody) == [], nobody


def test_a_switch_off_names_the_agent_even_after_it_was_retired(
    api, auth, world, worker, db_session, lead
) -> None:
    agent = tried_agent(api, auth, lead)
    second_admin(db_session, world)
    ok(switch_on(api, auth, agent))
    worker()
    ok(
        api.patch(
            f"{AGENTS}/{agent['agent_key']}",
            json={"enabled": False, "version": 1},
            headers=auth("alpha.admin"),
        )
    )
    assert api.post(f"{URL}/{agent['id']}/archive", headers=auth("alpha.admin")).status_code == 204
    worker()
    titles = [n["title"] for n in notifications(api, auth, "alpha.manager2")]
    assert f"AI agent switched off: {NAME} (custom agent)" in titles


def test_the_admins_hear_when_a_custom_agent_passes_80_percent_of_its_budget(
    api, auth, world, worker, db_session, lead
) -> None:
    agent = tried_agent(api, auth, lead)
    second_admin(db_session, world)
    ok(switch_on(api, auth, agent))
    ok(
        api.patch(
            f"{AGENTS}/{agent['agent_key']}",
            json={"monthly_token_budget": 1000, "version": 1},
            headers=auth("alpha.admin"),
        )
    )
    agents_api.record_usage(
        db_session,
        alpha(world),
        agent["agent_key"],
        input_tokens=850,
        output_tokens=0,
        limits=LIMITS,
        now=datetime.now(UTC),
    )
    db_session.flush()
    worker()
    titles = [n["title"] for n in notifications(api, auth, "alpha.manager2")]
    assert f"AI agent near its monthly limit (80 %): {NAME} (custom agent)" in titles


def test_an_event_about_an_agent_that_does_not_exist_here_tells_nobody(
    api, auth, world, worker, db_session
) -> None:
    second_admin(db_session, world)
    bind_tenant(db_session, alpha(world))
    publish(
        db_session,
        alpha(world),
        "agent.switched",
        {
            "agent": "custom_abcdefghijkl",  # no such agent in this organisation
            "state": "on",
            "actor_id": str(world.users["alpha.admin"].id),
        },
    )
    db_session.flush()
    worker()
    assert notifications(api, auth, "alpha.manager2") == []
