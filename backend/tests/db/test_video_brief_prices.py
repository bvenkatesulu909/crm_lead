# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Price facts in the video brief (ADR 0041, step VB1b) through the real API and PostgreSQL.

Uses the people and records of test_quotes_api.py: agent1 owns account A1 and writes its quotes;
agent2 owns A2. A lead of agent1 is converted to A1 here.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.leads.models import Lead
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    World,
    api,
    auth,
    new_quote,
    ok,
    step,
    to_sent,
    world,
)

LEADS = "/api/v1/leads"


def make_lead(committed_world: Session, world: World) -> str:
    agent = world.users["alpha.agent1"]
    lead = Lead(
        tenant_id=agent.tenant_id,
        first_name="Suresh",
        last_name="Rao",
        status="converted",
        owner_id=agent.id,
        converted_at=datetime.now(UTC),
        converted_account_id=world.ids["A1"],
        converted_contact_id=world.ids["C1"],
        preferred_language="en",
    )
    committed_world.add(lead)
    committed_world.commit()
    return str(lead.id)


def brief(api, auth, lead_id: str, user: str = "alpha.agent1", **params: Any) -> Any:
    return api.get(f"{LEADS}/{lead_id}/video-brief", params=params, headers=auth(user))


def approved(api, auth, world, **extra: Any) -> Any:
    quote = new_quote(api, auth, world, **extra)
    return ok(step(api, auth, "alpha.agent1", quote, "submit"))


def test_an_approved_quote_adds_cited_price_lines(api, auth, world, committed_world) -> None:
    lead = make_lead(committed_world, world)
    quote = approved(api, auth, world, internal_note="SECRET staff note", customer_note="Hi")
    response = brief(api, auth, lead, quote_id=quote["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    price = [s for s in body["script"] if s["kind"] == "price"]
    assert price and all(s["cites"][0].startswith("QT-") for s in price)
    assert any(k["kind"] == "price" and k["source"].startswith("QT-") for k in body["known"])
    assert "SECRET staff note" not in response.text


def test_a_sent_quote_works_too(api, auth, world, committed_world) -> None:
    lead = make_lead(committed_world, world)
    quote = to_sent(api, auth, world)
    assert brief(api, auth, lead, quote_id=quote["id"]).status_code == 200


def test_a_draft_quote_is_refused(api, auth, world, committed_world) -> None:
    lead = make_lead(committed_world, world)
    quote = new_quote(api, auth, world)
    response = brief(api, auth, lead, quote_id=quote["id"])
    assert response.status_code == 422
    assert response.json()["code"] == "video_brief_quote_not_ready"


def test_another_accounts_quote_is_not_found(api, auth, world, committed_world) -> None:
    lead = make_lead(committed_world, world)  # converted to A1
    other = new_quote(api, auth, world, user="alpha.agent2", account="A2")
    other = ok(step(api, auth, "alpha.agent2", other, "submit"))
    response = brief(api, auth, lead, quote_id=other["id"])
    assert response.status_code == 404
    assert response.json()["code"] == "quote_not_found"


def test_a_made_up_or_malformed_quote_id(api, auth, world, committed_world) -> None:
    lead = make_lead(committed_world, world)
    assert brief(api, auth, lead, quote_id=str(uuid.uuid4())).status_code == 404
    assert brief(api, auth, lead, quote_id="nope").status_code == 422


def test_a_colleague_and_another_organisation_cannot_use_the_quote(
    api, auth, world, committed_world
) -> None:
    lead = make_lead(committed_world, world)
    quote = approved(api, auth, world)
    for user in ("alpha.agent2", "beta.agent"):
        assert brief(api, auth, lead, user, quote_id=quote["id"]).status_code == 404
    assert brief(api, auth, lead, "alpha.manager", quote_id=quote["id"]).status_code == 200


def test_building_the_brief_with_a_quote_changes_nothing(api, auth, world, committed_world) -> None:
    lead = make_lead(committed_world, world)
    quote = approved(api, auth, world)
    url = f"/api/v1/quotes/{quote['id']}"
    before = api.get(url, headers=auth("alpha.agent1")).json()
    brief(api, auth, lead, quote_id=quote["id"])
    assert api.get(url, headers=auth("alpha.agent1")).json() == before


def test_a_lead_that_was_never_converted_has_no_quotes(api, auth, world, committed_world) -> None:
    agent = world.users["alpha.agent1"]
    lead = Lead(tenant_id=agent.tenant_id, last_name="Open", status="new", owner_id=agent.id)
    committed_world.add(lead)
    committed_world.commit()
    quote = approved(api, auth, world)
    assert brief(api, auth, str(lead.id), quote_id=quote["id"]).status_code == 404
