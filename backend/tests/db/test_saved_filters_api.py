# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Saved account filters through the real API (ADR 0042, BR-pre): saving, listing, sharing, changing
and deleting; who sees and changes what; limits; tenant isolation; made-up ids."""

import uuid
from typing import Any

import pytest

from app.modules.saved_filters import rules
from tests.db.test_quotes_api import api, auth, code_of, ok, world

URL = "/api/v1/saved-filters"
BODY: dict[str, Any] = {"name": "Big accounts", "params": {"segment": "enterprise"}}


def save(api: Any, auth: Any, who: str = "alpha.agent1", **changes: Any) -> Any:
    return api.post(URL, json=BODY | changes, headers=auth(who))


def saved(api: Any, auth: Any, who: str = "alpha.agent1", **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = ok(save(api, auth, who, **changes), 201)
    return body


def test_save_list_and_read_back(api, auth) -> None:
    item = saved(api, auth)
    assert item["name"] == "Big accounts"
    assert item["params"] == {"segment": "enterprise"}
    assert item["shared"] is False and item["mine"] is True and item["version"] == 1
    listing = ok(api.get(URL, headers=auth("alpha.agent1")))["items"]
    assert [f["id"] for f in listing] == [item["id"]]
    assert ok(api.get(f"{URL}/{item['id']}", headers=auth("alpha.agent1")))["id"] == item["id"]


def test_a_private_filter_is_invisible_to_colleagues_and_looks_missing(api, auth) -> None:
    item = saved(api, auth)
    for who in ("alpha.agent2", "alpha.manager", "alpha.admin"):
        assert ok(api.get(URL, headers=auth(who)))["items"] == []
        assert code_of(api.get(f"{URL}/{item['id']}", headers=auth(who))) == (
            404,
            "saved_filter_not_found",
        )
        assert code_of(api.delete(f"{URL}/{item['id']}", headers=auth(who)))[0] == 404


def test_a_made_up_id_is_not_found(api, auth) -> None:
    assert code_of(api.get(f"{URL}/{uuid.uuid4()}", headers=auth("alpha.agent1"))) == (
        404,
        "saved_filter_not_found",
    )


def test_sales_agents_cannot_share_but_managers_can(api, auth) -> None:
    assert code_of(save(api, auth, "alpha.agent1", shared=True))[0] == 403
    shared = saved(api, auth, "alpha.manager", shared=True)
    assert shared["shared"] is True
    for who in ("alpha.agent1", "alpha.agent2", "alpha.admin"):
        assert [f["id"] for f in ok(api.get(URL, headers=auth(who)))["items"]] == [shared["id"]]
    assert ok(api.get(URL, headers=auth("alpha.agent1")))["items"][0]["mine"] is False


def test_a_shared_filter_is_used_but_not_changed_by_others(api, auth) -> None:
    shared = saved(api, auth, "alpha.manager", shared=True)
    patch = {"version": 1, "name": "Mine now"}
    assert (
        code_of(api.patch(f"{URL}/{shared['id']}", json=patch, headers=auth("alpha.agent1")))[0]
        == 403
    )
    assert code_of(api.delete(f"{URL}/{shared['id']}", headers=auth("alpha.agent1")))[0] == 403


def test_a_tenant_admin_can_unshare_or_delete_someone_elses_shared_filter(api, auth) -> None:
    shared = saved(api, auth, "alpha.manager", shared=True)
    body = ok(
        api.patch(
            f"{URL}/{shared['id']}",
            json={"version": 1, "shared": False},
            headers=auth("alpha.admin"),
        )
    )
    assert body["shared"] is False
    # Now it is private to the manager again: the admin cannot even see it.
    assert code_of(api.get(f"{URL}/{shared['id']}", headers=auth("alpha.admin")))[0] == 404
    again = saved(api, auth, "alpha.manager", name="Second", shared=True)
    assert code_of(api.delete(f"{URL}/{again['id']}", headers=auth("alpha.admin")))[0] == 204


def test_an_admin_cannot_rewrite_someone_elses_shared_filter(api, auth) -> None:
    shared = saved(api, auth, "alpha.manager", shared=True)
    for change in ({"name": "Taken"}, {"params": {"segment": "non_profit"}}, {"shared": True}):
        r = api.patch(
            f"{URL}/{shared['id']}", json={"version": 1} | change, headers=auth("alpha.admin")
        )
        assert r.status_code == 403, change


def test_the_owner_can_rename_change_and_share(api, auth) -> None:
    item = saved(api, auth, "alpha.manager")
    body = ok(
        api.patch(
            f"{URL}/{item['id']}",
            json={
                "version": 1,
                "name": "Mid market",
                "params": {"segment": "mid_market", "country": "IN"},
                "shared": True,
            },
            headers=auth("alpha.manager"),
        )
    )
    assert body["name"] == "Mid market" and body["shared"] is True and body["version"] == 2
    assert body["params"] == {"segment": "mid_market", "country": "IN"}


def test_a_stale_version_is_a_conflict_and_nothing_changed_is_refused(api, auth) -> None:
    item = saved(api, auth)
    ok(
        api.patch(
            f"{URL}/{item['id']}", json={"version": 1, "name": "A"}, headers=auth("alpha.agent1")
        )
    )
    stale = api.patch(
        f"{URL}/{item['id']}", json={"version": 1, "name": "B"}, headers=auth("alpha.agent1")
    )
    assert code_of(stale) == (409, "version_conflict")
    same = api.patch(
        f"{URL}/{item['id']}", json={"version": 2, "name": "A"}, headers=auth("alpha.agent1")
    )
    assert code_of(same)[0] == 422


def test_the_owner_can_delete(api, auth) -> None:
    item = saved(api, auth)
    assert api.delete(f"{URL}/{item['id']}", headers=auth("alpha.agent1")).status_code == 204
    assert ok(api.get(URL, headers=auth("alpha.agent1")))["items"] == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"archived": "true"},
        {"limit": "500"},
        {"segment": "huge"},
        {"tenant_id": str(uuid.uuid4())},
        {"min_value": "5"},
    ],
)
def test_bad_parameters_are_refused(api, auth, params) -> None:
    assert code_of(save(api, auth, params=params)) == (422, "invalid_saved_filter")


@pytest.mark.parametrize("extra", ["owner_user_id", "tenant_id", "record_type", "id", "version"])
def test_the_client_cannot_choose_server_fields(api, auth, extra) -> None:
    assert save(api, auth, **{extra: str(uuid.uuid4())}).status_code == 422


def test_a_name_is_used_once_per_person_ignoring_capitals(api, auth) -> None:
    saved(api, auth)
    assert code_of(save(api, auth, name="BIG ACCOUNTS")) == (409, "saved_filter_name_taken")
    # A colleague may use the same name privately.
    saved(api, auth, "alpha.agent2")


def test_a_shared_name_is_unique_across_the_organisation(api, auth) -> None:
    saved(api, auth, "alpha.manager", shared=True)
    assert code_of(save(api, auth, "alpha.admin", shared=True)) == (409, "saved_filter_name_taken")


def test_a_person_can_keep_at_most_fifty(api, auth, monkeypatch) -> None:
    monkeypatch.setattr(rules, "MAX_PER_PERSON", 2)
    saved(api, auth, name="One")
    saved(api, auth, name="Two")
    assert code_of(save(api, auth, name="Three")) == (409, "saved_filter_limit")


def test_roles_without_account_access_are_refused(api, auth) -> None:
    assert api.get(URL, headers=auth("alpha.customer")).status_code == 403
    assert save(api, auth, "alpha.customer").status_code == 403
    assert api.get(URL).status_code == 401


def test_another_organisation_sees_nothing_and_cannot_touch_it(api, auth) -> None:
    mine = saved(api, auth, "alpha.manager", shared=True)
    assert ok(api.get(URL, headers=auth("beta.admin")))["items"] == []
    other = headers = auth("beta.admin")
    assert code_of(api.get(f"{URL}/{mine['id']}", headers=other))[0] == 404
    assert code_of(api.delete(f"{URL}/{mine['id']}", headers=headers))[0] == 404
    # The same shared name in the other organisation is no clash.
    saved(api, auth, "beta.admin", shared=True)
