# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Batch research through the real API (ADR 0042, BR4): estimate, start with the confirmed cost,
list, read, cancel and retry; who may, what a client cannot choose, other organisations, ID
tampering, the limits and the two switches. The worker is run by calling its step directly with a
scripted model."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.accounts.models import Account
from app.modules.research_batches import worker
from tests.db.test_approvals import alpha
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world
from tests.db.test_research_batch_service import WORST, make_settings
from tests.db.test_research_batch_worker import Writer

URL = "/api/v1/research-batches"
AGENTS = "/api/v1/agents"


def switch(api: Any, auth: Headers, key: str, who: str = "alpha.admin", on: bool = True) -> None:
    current = ok(api.get(f"{AGENTS}/{key}", headers=auth(who)))
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    ok(api.patch(f"{AGENTS}/{key}", json=body, headers=auth(who)))


@pytest.fixture
def ready(api, auth) -> None:
    switch(api, auth, "research_batches")
    switch(api, auth, "account_research")


def rows(world: World, *keys: str, **extra: Any) -> dict[str, Any]:
    return {"source": "rows", "account_ids": [str(world.ids[k]) for k in keys]} | extra


def estimate(api: Any, auth: Headers, body: dict[str, Any], who: str = "alpha.manager") -> Any:
    return api.post(f"{URL}/estimate", json=body, headers=auth(who))


def start(api: Any, auth: Headers, body: dict[str, Any], confirmed: int, who="alpha.manager"):
    return api.post(URL, json=body | {"confirmed_upper_bound_tokens": confirmed}, headers=auth(who))


def started(
    api: Any, auth: Headers, world: World, *keys: str, who="alpha.manager"
) -> dict[str, Any]:
    body = rows(world, *keys)
    return ok(start(api, auth, body, len(keys) * WORST, who), 201)  # type: ignore[no-any-return]


def run_steps(session: Session, world: World, batch_id: str, model: Any, times: int = 9) -> None:
    bind_tenant(session, alpha(world))
    for _ in range(times):
        result = worker.run_step(session, alpha(world), uuid.UUID(batch_id), make_settings(), model)
        if not result.more:
            return


# --- the estimate -------------------------------------------------------------


def test_the_estimate_counts_accounts_reuse_and_cost_and_writes_nothing(
    api, auth, world, ready
) -> None:
    body = estimate(api, auth, rows(world, "A1", "A2"))
    found = ok(body)
    assert found["accounts"] == 2 and found["calling_model"] == 2 and found["reused"] == 0
    assert found["not_available"] == 0 and found["archived"] == 0
    assert found["upper_bound_tokens"] == 2 * WORST == found["cap_tokens"]
    assert found["worst_case_tokens_per_account"] == WORST
    assert found["estimated_cost_usd"] is None  # no price configured: unknown, never free
    assert ok(api.get(URL, headers=auth("alpha.manager")))["total"] == 0


@pytest.mark.parametrize("who", ["alpha.manager", "alpha.admin"])
def test_managers_and_administrators_may_ask(api, auth, world, ready, who) -> None:
    assert ok(estimate(api, auth, rows(world, "A1"), who))["accounts"] == 1


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support", "alpha.customer"])
def test_nobody_else_may_use_any_endpoint(api, auth, world, ready, who) -> None:
    assert estimate(api, auth, rows(world, "A1"), who).status_code == 403
    assert start(api, auth, rows(world, "A1"), WORST, who).status_code == 403
    assert api.get(URL, headers=auth(who)).status_code == 403
    assert api.get(f"{URL}/{uuid.uuid4()}", headers=auth(who)).status_code == 403
    assert api.post(f"{URL}/{uuid.uuid4()}/cancel", headers=auth(who)).status_code == 403


def test_a_request_without_a_token_is_refused(api, world) -> None:
    assert (
        api.post(f"{URL}/estimate", json={"source": "rows", "account_ids": []}).status_code == 401
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": str(uuid.uuid4())},
        {"created_by_user_id": str(uuid.uuid4())},
        {"token_cap": 1},
        {"status": "finished"},
        {"account_count": 1},
    ],
)
def test_the_client_cannot_choose_server_fields(api, auth, world, ready, extra) -> None:
    assert estimate(api, auth, rows(world, "A1", **extra)).status_code == 422
    assert start(api, auth, rows(world, "A1", **extra), WORST).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"source": "magic", "account_ids": []},
        {"source": "rows"},  # no accounts
        {"source": "filter"},  # no filter
    ],
)
def test_a_selection_must_make_sense(api, auth, world, ready, body) -> None:
    assert estimate(api, auth, body).status_code in (422,)


def test_ids_the_person_cannot_read_are_only_counted(api, auth, world, ready) -> None:
    body = rows(world, "A1", "B1")  # B1 is another organisation's account
    body["account_ids"].append(str(uuid.uuid4()))  # and one that does not exist
    found = ok(estimate(api, auth, body))
    assert found["accounts"] == 1 and found["not_available"] == 2


def test_another_persons_private_saved_filter_looks_missing(api, auth, world, ready) -> None:
    private = ok(
        api.post(
            "/api/v1/saved-filters",
            json={"name": "Theirs", "params": {"status": "active"}},
            headers=auth("alpha.manager2"),
        ),
        201,
    )
    body = {"source": "filter", "saved_filter_id": private["id"]}
    answer = estimate(api, auth, body)
    assert code_of(answer) == (404, "saved_filter_not_found")


def test_a_saved_filter_picks_accounts_as_the_list_would(api, auth, world, ready) -> None:
    saved = ok(
        api.post(
            "/api/v1/saved-filters",
            json={"name": "Active", "params": {"status": "active"}},
            headers=auth("alpha.manager"),
        ),
        201,
    )
    found = ok(estimate(api, auth, {"source": "filter", "saved_filter_id": saved["id"]}))
    assert found["accounts"] >= 2


def test_both_switches_are_needed(api, auth, world) -> None:
    assert code_of(estimate(api, auth, rows(world, "A1")))[0] == 503  # nothing switched on
    switch(api, auth, "research_batches")
    assert code_of(estimate(api, auth, rows(world, "A1")))[0] == 503  # research still off
    switch(api, auth, "account_research")
    assert estimate(api, auth, rows(world, "A1")).status_code == 200


# --- starting -----------------------------------------------------------------


def test_a_started_batch_is_running_with_its_accounts_queued(api, auth, world, ready) -> None:
    batch = started(api, auth, world, "A1", "A2")
    assert batch["status"] == "running" and batch["mine"] is True
    assert batch["account_count"] == 2 and batch["token_cap"] == 2 * WORST
    assert batch["counts"]["queued"] == 2 and batch["tokens_used"] == 0
    assert batch["cancel_requested"] is False and batch["finished_at"] is None


def test_a_stale_confirmation_is_refused_and_nothing_is_started(api, auth, world, ready) -> None:
    answer = start(api, auth, rows(world, "A1", "A2"), WORST)  # shown for one account, now two
    assert code_of(answer) == (409, "estimate_changed")
    assert ok(api.get(URL, headers=auth("alpha.manager")))["total"] == 0


def test_more_than_the_cap_is_a_clear_refusal(api, auth, world, ready) -> None:
    body = rows(world, "A1")
    body["account_ids"] = [str(uuid.uuid4()) for _ in range(101)]
    assert code_of(estimate(api, auth, body)) == (422, "batch_too_large")


def test_one_running_batch_per_person_and_the_second_is_refused(api, auth, world, ready) -> None:
    started(api, auth, world, "A1")
    assert code_of(estimate(api, auth, rows(world, "A2"))) == (429, "research_batch_limit")
    assert code_of(start(api, auth, rows(world, "A2"), WORST)) == (429, "research_batch_limit")
    # A colleague is a different person and may start one.
    started(api, auth, world, "A2", who="alpha.manager2")


# --- reading ------------------------------------------------------------------


def test_a_colleague_manager_can_read_a_batch_and_the_list(api, auth, world, ready) -> None:
    batch = started(api, auth, world, "A1", "A2")
    one = ok(api.get(f"{URL}/{batch['id']}", headers=auth("alpha.manager2")))
    assert one["mine"] is False and one["id"] == batch["id"]
    assert [i["position"] for i in one["items"]] == [1, 2]
    assert [i["account_name"] for i in one["items"]] == ["Quote A1", "Quote A2"]
    listing = ok(api.get(URL, headers=auth("alpha.manager2")))
    assert [b["id"] for b in listing["items"]] == [batch["id"]] and listing["total"] == 1


def test_an_account_the_viewer_may_not_read_has_no_name(
    api, auth, world, ready, db_session
) -> None:
    batch = started(api, auth, world, "A1", "A2")
    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(Account).where(Account.id == world.ids["A1"]).values(deleted_at=func.now())
    )
    one = ok(api.get(f"{URL}/{batch['id']}", headers=auth("alpha.manager")))
    assert [i["account_name"] for i in one["items"]] == [None, "Quote A2"]


def test_another_organisation_sees_nothing(api, auth, world, ready) -> None:
    batch = started(api, auth, world, "A1")
    other = auth("beta.admin")
    assert code_of(api.get(f"{URL}/{batch['id']}", headers=other)) == (
        404,
        "research_batch_not_found",
    )
    assert code_of(api.post(f"{URL}/{batch['id']}/cancel", headers=other)) == (
        404,
        "research_batch_not_found",
    )
    assert ok(api.get(URL, headers=other))["items"] == []


def test_a_made_up_batch_is_not_found(api, auth, world, ready) -> None:
    assert code_of(api.get(f"{URL}/{uuid.uuid4()}", headers=auth("alpha.manager")))[0] == 404
    assert api.get(f"{URL}/not-an-id", headers=auth("alpha.manager")).status_code == 422


# --- the worker's results show up ---------------------------------------------


def test_finished_items_show_their_brief_figures_and_the_batch_its_tokens(
    api, auth, world, ready, db_session
) -> None:
    batch = started(api, auth, world, "A1", "A2")
    run_steps(db_session, world, batch["id"], Writer(tokens=(300, 200)))
    one = ok(api.get(f"{URL}/{batch['id']}", headers=auth("alpha.manager")))
    assert one["status"] == "finished" and one["tokens_used"] == 1000
    assert one["counts"]["done"] == 2 and one["finished_at"] is not None
    for item in one["items"]:
        assert item["status"] == "done" and item["brief"]["tokens"] == 500
        assert item["brief"]["sentences"] >= 1 and "text" not in item["brief"]


# --- cancel -------------------------------------------------------------------


def test_a_running_batch_can_be_stopped_by_its_starter_or_a_colleague(
    api, auth, world, ready
) -> None:
    batch = started(api, auth, world, "A1", "A2")
    stopped = ok(api.post(f"{URL}/{batch['id']}/cancel", headers=auth("alpha.manager2")))
    assert stopped["cancel_requested"] is True and stopped["status"] == "running"
    again = ok(api.post(f"{URL}/{batch['id']}/cancel", headers=auth("alpha.manager")))
    assert again["cancel_requested"] is True  # asking twice is harmless


def test_the_worker_then_ends_it_as_cancelled(api, auth, world, ready, db_session) -> None:
    batch = started(api, auth, world, "A1", "A2")
    ok(api.post(f"{URL}/{batch['id']}/cancel", headers=auth("alpha.manager")))
    writer = Writer()
    run_steps(db_session, world, batch["id"], writer)
    one = ok(api.get(f"{URL}/{batch['id']}", headers=auth("alpha.manager")))
    assert one["status"] == "cancelled" and one["counts"]["not_run"] == 2
    assert writer.calls == 0


def test_an_ended_batch_cannot_be_stopped(api, auth, world, ready, db_session) -> None:
    batch = started(api, auth, world, "A1")
    run_steps(db_session, world, batch["id"], Writer())
    answer = api.post(f"{URL}/{batch['id']}/cancel", headers=auth("alpha.manager"))
    assert code_of(answer) == (409, "research_batch_not_running")


# --- retry --------------------------------------------------------------------


def test_the_failed_accounts_can_be_tried_again_as_a_new_batch(
    api, auth, world, ready, db_session
) -> None:
    batch = started(api, auth, world, "A1", "A2")
    # Still running: nothing to retry yet.
    still = api.post(
        f"{URL}/{batch['id']}/retry/estimate",
        json={"which": "failed"},
        headers=auth("alpha.manager"),
    )
    assert code_of(still) == (409, "research_batch_running")
    run_steps(db_session, world, batch["id"], Writer(mode="nosource"))  # both fail
    found = ok(
        api.post(
            f"{URL}/{batch['id']}/retry/estimate",
            json={"which": "failed"},
            headers=auth("alpha.manager"),
        )
    )
    assert found["accounts"] == 2
    new = ok(
        api.post(
            f"{URL}/{batch['id']}/retry",
            json={"which": "failed", "confirmed_upper_bound_tokens": 2 * WORST},
            headers=auth("alpha.manager"),
        ),
        201,
    )
    assert new["id"] != batch["id"] and new["status"] == "running" and new["account_count"] == 2
    assert new["counts"]["queued"] == 2


def test_nothing_to_retry_and_a_bad_choice_are_refused(api, auth, world, ready, db_session) -> None:
    batch = started(api, auth, world, "A1")
    run_steps(db_session, world, batch["id"], Writer())  # it worked: nothing failed
    manager = auth("alpha.manager")
    empty = api.post(
        f"{URL}/{batch['id']}/retry/estimate", json={"which": "failed"}, headers=manager
    )
    assert code_of(empty) == (422, "empty_selection")
    wrong = api.post(
        f"{URL}/{batch['id']}/retry/estimate", json={"which": "everything"}, headers=manager
    )
    assert wrong.status_code == 422


def test_a_retry_needs_the_confirmed_cost_like_any_batch(
    api, auth, world, ready, db_session
) -> None:
    batch = started(api, auth, world, "A1", "A2")
    run_steps(db_session, world, batch["id"], Writer(mode="nosource"))
    answer = api.post(
        f"{URL}/{batch['id']}/retry",
        json={"which": "failed", "confirmed_upper_bound_tokens": 10},
        headers=auth("alpha.manager"),
    )
    assert code_of(answer) == (409, "estimate_changed")


def test_another_organisation_cannot_retry_a_batch(api, auth, world, ready, db_session) -> None:
    batch = started(api, auth, world, "A1")
    run_steps(db_session, world, batch["id"], Writer(mode="nosource"))
    answer = api.post(
        f"{URL}/{batch['id']}/retry/estimate", json={"which": "failed"}, headers=auth("beta.admin")
    )
    assert code_of(answer) == (404, "research_batch_not_found")
