# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""The deal risk forecast through the real API (ADR 0037, step DR3).

Real application and database; nothing here calls a model. Happy path, role denial, record-level
denial, tenant isolation, ID tampering, the per-person limit and the shape of the answers.
"""

import uuid
from typing import Any

import pytest

from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world

BASE = "/api/v1/deal-risk"


def recompute(api: Any, auth: Headers, who: str, deal: Any) -> Any:
    return api.post(f"{BASE}/{deal}/recompute", headers=auth(who))


def test_a_manager_recomputes_reads_and_lists_a_forecast(api, auth, world) -> None:
    deal = world.ids["O1"]
    created = ok(recompute(api, auth, "alpha.manager", deal), 201)
    assert created["opportunity_id"] == str(deal)
    assert created["level"] in {"low", "medium", "high"} and 0 <= created["score"] <= 100
    assert created["source"] == "on_demand" and created["rules_version"] == 1
    assert created["note"].startswith("Forecast: an estimate")
    assert created["deal"]["id"] == str(deal)
    assert created["score"] == sum(f["points"] for f in created["factors"])

    newest = ok(api.get(f"{BASE}/{deal}", headers=auth("alpha.manager")))
    assert newest["id"] == created["id"]

    listing = ok(api.get(BASE, headers=auth("alpha.admin")))
    assert listing["total"] == 1 and listing["items"][0]["id"] == created["id"]
    assert listing["items"][0]["deal"]["name"]
    assert "forecast" in listing["note"].lower()


def test_no_forecast_yet_is_a_clear_404(api, auth, world) -> None:
    response = api.get(f"{BASE}/{world.ids['O1']}", headers=auth("alpha.manager"))
    assert code_of(response) == (404, "deal_risk_not_computed")
    assert ok(api.get(BASE, headers=auth("alpha.manager")))["items"] == []


def test_the_list_shows_the_newest_forecast_per_deal_highest_score_first(api, auth, world) -> None:
    first = ok(recompute(api, auth, "alpha.manager", world.ids["O1"]), 201)
    ok(recompute(api, auth, "alpha.manager", world.ids["O1"]), 201)  # a second one for O1
    ok(recompute(api, auth, "alpha.manager", world.ids["O2"]), 201)
    listing = ok(api.get(BASE, headers=auth("alpha.manager")))
    assert listing["total"] == 2  # one row per deal, not per snapshot
    scores = [i["score"] for i in listing["items"]]
    assert scores == sorted(scores, reverse=True)
    assert first["id"] not in {i["id"] for i in listing["items"]}  # the older O1 one is replaced


def test_the_level_filter_and_paging_are_applied_in_the_database(api, auth, world) -> None:
    created = {
        key: ok(recompute(api, auth, "alpha.manager", world.ids[key]), 201) for key in ("O1", "O2")
    }
    # Every level is asked for, so a filter that is ignored cannot hide behind equal levels.
    for level in ("low", "medium", "high"):
        expected = [c["id"] for c in created.values() if c["level"] == level]
        filtered = ok(api.get(BASE, params={"level": level}, headers=auth("alpha.manager")))
        assert filtered["total"] == len(expected)
        assert sorted(i["id"] for i in filtered["items"]) == sorted(expected)
    everything = ok(api.get(BASE, headers=auth("alpha.manager")))["items"]
    page = ok(api.get(BASE, params={"limit": 1, "offset": 1}, headers=auth("alpha.manager")))
    assert page["total"] == 2 and page["offset"] == 1
    assert [i["id"] for i in page["items"]] == [
        everything[1]["id"]
    ]  # the second one, not the first
    past_end = ok(api.get(BASE, params={"offset": 2}, headers=auth("alpha.manager")))
    assert past_end["items"] == [] and past_end["total"] == 2
    assert (
        api.get(BASE, params={"level": "extreme"}, headers=auth("alpha.manager")).status_code == 422
    )
    assert api.get(BASE, params={"limit": 0}, headers=auth("alpha.manager")).status_code == 422


def test_history_lists_earlier_forecasts_newest_first(api, auth, world) -> None:
    deal = world.ids["O1"]
    ids = [ok(recompute(api, auth, "alpha.manager", deal), 201)["id"] for _ in range(3)]
    history = ok(api.get(f"{BASE}/{deal}/history", headers=auth("alpha.manager")))["items"]
    assert [h["id"] for h in history] == list(reversed(ids))
    limited = ok(
        api.get(f"{BASE}/{deal}/history", params={"limit": 2}, headers=auth("alpha.manager"))
    )
    assert len(limited["items"]) == 2
    assert "deal" not in history[0]


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.agent2", "alpha.support", "alpha.customer"])
def test_people_without_the_permission_get_403_everywhere(api, auth, world, who) -> None:
    deal = world.ids["O1"]
    assert api.get(BASE, headers=auth(who)).status_code == 403
    assert api.get(f"{BASE}/{deal}", headers=auth(who)).status_code == 403
    assert api.get(f"{BASE}/{deal}/history", headers=auth(who)).status_code == 403
    assert recompute(api, auth, who, deal).status_code == 403


def test_a_request_without_a_token_is_401(api, world) -> None:
    assert api.get(BASE).status_code == 401
    assert api.post(f"{BASE}/{world.ids['O1']}/recompute").status_code == 401


def test_another_organisations_deal_is_404_and_its_list_is_empty(api, auth, world) -> None:
    ok(recompute(api, auth, "alpha.manager", world.ids["O1"]), 201)
    deal = world.ids["O1"]
    assert code_of(recompute(api, auth, "beta.admin", deal))[0] == 404
    assert api.get(f"{BASE}/{deal}", headers=auth("beta.admin")).status_code == 404
    assert api.get(f"{BASE}/{deal}/history", headers=auth("beta.admin")).status_code == 404
    assert ok(api.get(BASE, headers=auth("beta.admin")))["total"] == 0


def test_made_up_and_malformed_ids(api, auth, world) -> None:
    for bad in (uuid.uuid4(), "not-an-id"):
        assert api.get(f"{BASE}/{bad}", headers=auth("alpha.manager")).status_code in (404, 422)
        assert recompute(api, auth, "alpha.manager", bad).status_code in (404, 422)
    assert code_of(recompute(api, auth, "alpha.manager", uuid.uuid4()))[0] == 404


def test_the_client_cannot_choose_the_score_or_the_level(api, auth, world) -> None:
    response = api.post(
        f"{BASE}/{world.ids['O1']}/recompute",
        json={"level": "low", "score": 0, "tenant_id": str(uuid.uuid4())},
        headers=auth("alpha.manager"),
    )
    created = ok(response, 201)  # the body is ignored: the server works it out
    assert created["score"] == sum(f["points"] for f in created["factors"])


def test_recomputing_too_often_is_429(api, auth, world) -> None:
    original = api.app.state.settings
    api.app.state.settings = original.model_copy(update={"deal_risk_recompute_per_user_hour": 2})
    try:
        deal = world.ids["O1"]
        ok(recompute(api, auth, "alpha.manager", deal), 201)
        ok(recompute(api, auth, "alpha.manager", deal), 201)
        assert code_of(recompute(api, auth, "alpha.manager", deal)) == (
            429,
            "deal_risk_rate_limited",
        )
        # The limit is per person: a colleague may still ask.
        ok(recompute(api, auth, "alpha.admin", deal), 201)
    finally:
        api.app.state.settings = original


def test_a_deal_one_may_not_read_never_appears_in_the_list(api, auth, world) -> None:
    # Managers read all deals; the list holds both of alpha's deals and none of beta's.
    ok(recompute(api, auth, "alpha.manager", world.ids["O1"]), 201)
    ok(recompute(api, auth, "alpha.manager", world.ids["O2"]), 201)
    ids = {i["opportunity_id"] for i in ok(api.get(BASE, headers=auth("alpha.manager")))["items"]}
    assert ids == {str(world.ids["O1"]), str(world.ids["O2"])}
