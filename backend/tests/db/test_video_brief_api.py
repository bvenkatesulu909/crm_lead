# ruff: noqa: F811 - pytest fixtures imported from test_leads_api are used as parameters
"""The video brief (ADR 0041, step VB1) through the real API and database.

tenant ALPHA: admin, manager, agent1, agent2 (sales agents), support, customer. BETA: admin, agent.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.modules.buyer_memory.models import BuyerMemoryItem
from tests.db.test_leads_api import api, auth, create, people  # noqa: F401 - fixtures

LEADS = "/api/v1/leads"
AGENT = "alpha.agent1"


def brief(api, auth, lead_id: str, /, user: str = AGENT, **params: Any) -> Any:
    return api.get(f"{LEADS}/{lead_id}/video-brief", params=params, headers=auth(user))


def ok(api, auth, lead_id: str, /, user: str = AGENT, **params: Any) -> dict[str, Any]:
    response = brief(api, auth, lead_id, user, **params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def lead(api, auth) -> dict[str, Any]:
    made = create(
        api, auth, AGENT, first_name="Suresh", last_name="Rao", email="suresh@example.test",
        phone="98480 12345", source="web", property_type="apartment",
        budget_min_inr=12_000_000, budget_max_inr=15_000_000, location="Kokapet, Hyderabad",
        preferred_language="te",
    )  # fmt: skip
    for body in (
        {"key": "budget", "value": "Up to 1.5 Cr", "status": "fact",
         "source": "buyer_confirmed", "quote": "Our budget is one and a half crore."},
        {"key": "timeline", "value": "Within six months", "status": "assumption",
         "reason": "Sounded in a hurry"},
    ):  # fmt: skip
        r = api.post(f"{LEADS}/{made['id']}/memory", json=body, headers=auth(AGENT))
        assert r.status_code == 201, r.text
    return made


def test_the_brief_is_built_from_cited_facts_and_the_buyers_language(api, auth, lead) -> None:
    body = ok(api, auth, lead["id"])
    assert body["first_name"] == "Suresh"
    assert body["language"] == "te"  # the lead's preferred language is the default
    kinds = {(k["kind"], k["key"]) for k in body["known"]}
    assert ("fact", "budget") in kinds and ("assumption", "timeline") in kinds
    assert ("form", "property_type") in kinds
    assert body["must_not_say"] and body["must_say"] and body["consent_notes"]
    assert body["words"] <= body["word_target"]


def test_the_choices_can_be_changed(api, auth, lead) -> None:
    body = ok(api, auth, lead["id"], language="hi", goal="after_visit", tone="brisk", length=30)
    assert (body["language"], body["goal"], body["tone"], body["length_seconds"]) == (
        "hi", "after_visit", "brisk", 30,
    )  # fmt: skip
    assert body["word_target"] == 75


def test_no_phone_e_mail_or_last_name_is_in_the_brief(api, auth, lead) -> None:
    text = api.get(f"{LEADS}/{lead['id']}/video-brief", headers=auth(AGENT)).text
    for secret in ("98480", "suresh@example.test", "Rao"):
        assert secret not in text


@pytest.mark.parametrize(
    "params",
    [{"language": "fr"}, {"tone": "angry"}, {"goal": "spam"}, {"length": 45}],
)
def test_values_outside_the_lists_are_422(api, auth, lead, params) -> None:
    assert brief(api, auth, lead["id"], **params).status_code == 422


def test_building_the_brief_writes_nothing_at_all(api, auth, lead, db_session: Session) -> None:
    def counts() -> tuple[int | None, int | None]:
        return (
            db_session.scalar(select(func.count()).select_from(BuyerMemoryItem)),
            db_session.scalar(select(func.count()).select_from(AuditLog)),
        )

    before = counts()
    ok(api, auth, lead["id"])
    assert counts() == before


@pytest.mark.parametrize("user", ["alpha.support", "alpha.customer"])
def test_roles_without_lead_access_are_refused(api, auth, lead, user) -> None:
    assert brief(api, auth, lead["id"], user).status_code == 403


def test_no_token_means_401(api, lead) -> None:
    assert api.get(f"{LEADS}/{lead['id']}/video-brief").status_code == 401


def test_a_colleague_cannot_use_my_lead_but_a_manager_can(api, auth, lead) -> None:
    assert brief(api, auth, lead["id"], "alpha.agent2").status_code == 404
    assert brief(api, auth, lead["id"], "alpha.manager").status_code == 200


def test_another_organisation_gets_404(api, auth, lead) -> None:
    for user in ("beta.admin", "beta.agent"):
        assert brief(api, auth, lead["id"], user).status_code == 404


def test_made_up_and_malformed_ids(api, auth) -> None:
    assert brief(api, auth, str(uuid.uuid4())).status_code == 404
    assert brief(api, auth, "not-an-id").status_code == 422


def test_what_the_server_decides_cannot_be_asked_for(api, auth, lead) -> None:
    body = ok(api, auth, lead["id"], tenant_id=str(uuid.uuid4()), facts="Invented price 1 Cr")
    assert "Invented price" not in str(body)
