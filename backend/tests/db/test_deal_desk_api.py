# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""The deal desk through the real API (ADR 0024, step DD3).

Real application, real database, the real agent registry and approvals; only the model is the
scripted fake the module ships for local demos (``CRM_AI_PROVIDER=fake``), put on the app.
"""

import uuid
from typing import Any

import pytest

from app.modules.deal_desk.llm import FakeDealDeskModel
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, lines, new_quote, ok, world

URL = "/api/v1/deal-desk/reviews"


class Counting(FakeDealDeskModel):
    def __init__(self) -> None:
        self.calls = 0

    def reply(self, **kw: Any) -> Any:  # type: ignore[override]
        self.calls += 1
        return super().reply(**kw)


def use(api: Any) -> Counting:
    model = Counting()
    api.app.state.deal_desk_model = model
    return model


def switch(api: Any, auth: Headers, on: bool = True) -> None:
    current = ok(api.get("/api/v1/agents/deal_desk", headers=auth("alpha.admin")))
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    ok(api.patch("/api/v1/agents/deal_desk", json=body, headers=auth("alpha.admin")))


def review(api: Any, auth: Headers, who: str, deal: Any, **extra: Any) -> Any:
    return api.post(URL, json={"opportunity_id": str(deal), **extra}, headers=auth(who))


def listed(api: Any, auth: Headers, who: str, deal: Any) -> Any:
    return api.get(URL, params={"opportunity_id": str(deal)}, headers=auth(who))


@pytest.fixture
def deal(api, auth, world) -> uuid.UUID:
    # A quote above the 10 % approval limit, so the fake pricing reviewer has an "act" finding.
    new_quote(
        api, auth, world, opportunity_id=str(world.ids["O1"]), lines=lines(world, ("P1", "3", "12"))
    )
    switch(api, auth)
    return world.ids["O1"]


def test_a_review_through_the_api(api, auth, world, deal) -> None:
    model = use(api)
    body = ok(review(api, auth, "alpha.agent1", deal), 201)
    assert model.calls == 4
    assert body["opportunity_id"] == str(deal)
    assert set(body["reviewers"]) == {"pricing", "account", "momentum"}
    over = [f for f in body["findings"] if "above the approval limit" in f["text"]]
    assert over and over[0]["severity"] == "act" and over[0]["records"][0]["type"] == "quote"
    assert 1 <= len(body["proposals"]) <= 2
    assert all(p["link"] == f"/approvals/{p['id']}" for p in body["proposals"])
    assert body["blocked_messages"] == []

    items = ok(listed(api, auth, "alpha.manager", deal))["items"]
    assert [i["id"] for i in items] == [body["id"]]
    assert "blocked_messages" not in items[0]

    # The proposal is a pending task on the deal, waiting for someone else.
    first = ok(
        api.get(
            f"/api/v1/approvals/actions/{body['proposals'][0]['id']}", headers=auth("alpha.manager")
        )
    )
    assert (first["status"], first["target_type"], first["agent"]) == (
        "pending",
        "opportunity",
        "deal_desk",
    )


def test_off_by_default_is_503_and_no_model_is_asked(api, auth, world) -> None:
    model = use(api)
    assert code_of(review(api, auth, "alpha.agent1", world.ids["O1"])) == (503, "agent_unavailable")
    assert model.calls == 0


@pytest.mark.parametrize("who", ["alpha.agent2", "beta.agent"])
def test_a_deal_the_asker_may_not_read_is_404(api, auth, world, deal, who) -> None:
    model = use(api)
    assert code_of(review(api, auth, who, deal))[0] == 404
    assert code_of(listed(api, auth, who, deal))[0] == 404
    assert model.calls == 0


def test_a_made_up_deal_is_404(api, auth, world, deal) -> None:
    use(api)
    assert code_of(review(api, auth, "alpha.manager", uuid.uuid4()))[0] == 404
    assert code_of(listed(api, auth, "alpha.manager", uuid.uuid4()))[0] == 404


@pytest.mark.parametrize("who", ["alpha.support", "alpha.customer"])
def test_people_without_the_permission_get_403(api, auth, world, deal, who) -> None:
    use(api)
    assert code_of(review(api, auth, who, deal))[0] == 403


@pytest.mark.parametrize(
    "extra",
    [{"tenant_id": str(uuid.uuid4())}, {"requested_by_user_id": str(uuid.uuid4())}, {"brief": "x"}],
)
def test_nothing_but_the_deal_is_accepted(api, auth, world, deal, extra) -> None:
    use(api)
    assert code_of(review(api, auth, "alpha.agent1", deal, **extra))[0] == 422


def test_a_second_review_within_the_hour_is_429(api, auth, world, deal) -> None:
    use(api)
    ok(review(api, auth, "alpha.agent1", deal), 201)
    model = use(api)
    assert code_of(review(api, auth, "alpha.agent1", deal)) == (429, "deal_desk_rate_limited")
    assert model.calls == 0
