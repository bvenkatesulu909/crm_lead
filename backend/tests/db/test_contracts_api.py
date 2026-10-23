"""Contracts and renewals, step C2: the API through the real stack and PostgreSQL.

Uses the quotes test world (tests/db/test_quotes_api.py):
tenant ALPHA: admin, manager, manager2, agent1 (owns A1, contact C1, deal O1), agent2 (owns
              A2, contact C2, deal O2), support, customer -> A1
tenant BETA:  admin, agent (owns B1)
"""

# ruff: noqa: F811 - the imported fixtures are used as test parameters

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.outbox import OutboxJob
from tests.db.test_quotes_api import (  # noqa: F401
    api,
    auth,
    code_of,
    new_quote,
    ok,
    world,
)

CONTRACTS = "/api/v1/contracts"
TODAY = datetime.now(UTC).date()


def new_contract(api, auth, world, user="alpha.agent1", account="A1", **extra: Any) -> Any:
    body = {
        "account_id": str(world.ids[account]),
        "title": "Support agreement",
        "start_date": str(TODAY),
        "end_date": str(TODAY + timedelta(days=365)),
        "total_value": "12000.50",
        **extra,
    }
    return ok(api.post(CONTRACTS, json=body, headers=auth(user)), 201)


def step(api, auth, user, contract, action, **body: Any):
    return api.post(
        f"{CONTRACTS}/{contract['id']}/{action}",
        json={"version": contract["version"], **body},
        headers=auth(user),
    )


def active(api, auth, world, **extra: Any) -> Any:
    draft = new_contract(api, auth, world, **extra)
    return ok(step(api, auth, "alpha.manager", draft, "activate"))


# === Happy path ===================================================================================


def test_an_agent_creates_reads_and_lists_a_draft_on_their_own_account(api, auth, world) -> None:
    created = new_contract(api, auth, world)
    assert created["label"] == "CT-0001"
    assert created["status"] == "draft"
    assert created["version"] == 1
    assert created["owner_id"] == str(world.users["alpha.agent1"].id)
    assert created["account_name"] == "Quote A1"
    assert created["total_value"] == "12000.50"
    assert created["currency"] == "EUR"
    assert created["billing_frequency"] == "annually"
    assert created["renewal_date"] == str(TODAY + timedelta(days=365 - 30))
    assert created["days_to_end"] == 365

    one = ok(api.get(f"{CONTRACTS}/{created['id']}", headers=auth("alpha.agent1")))
    assert one["id"] == created["id"] and one["renewed_to_id"] is None
    page = ok(api.get(CONTRACTS, headers=auth("alpha.agent1")))
    assert [c["id"] for c in page["items"]] == [created["id"]] and page["total"] == 1
    history = ok(api.get(f"{CONTRACTS}/{created['id']}/history", headers=auth("alpha.agent1")))
    assert [(e["event_type"], e["to_status"]) for e in history] == [("created", "draft")]


def test_numbers_count_up_inside_each_organisation(api, auth, world) -> None:
    assert new_contract(api, auth, world)["label"] == "CT-0001"
    assert new_contract(api, auth, world, title="Second")["label"] == "CT-0002"
    beta = new_contract(api, auth, world, user="beta.agent", account="B1")
    assert beta["label"] == "CT-0001"  # numbering is per organisation


# === Validation ===================================================================================


def test_bad_input_is_refused(api, auth, world) -> None:
    base = {"account_id": str(world.ids["A1"]), "title": "X"}
    bad = [
        {**base, "title": ""},
        {**base, "start_date": "2027-02-01", "end_date": "2027-01-01"},
        {**base, "currency": "euro"},
        {**base, "total_value": "-5"},
        {**base, "total_value": "10.123"},
        {**base, "renewal_notice_days": 400},
        {**base, "renewal_term_months": 0},
        {**base, "billing_frequency": "daily"},
        {"title": "no account"},
    ]
    for body in bad:
        assert api.post(CONTRACTS, json=body, headers=auth("alpha.agent1")).status_code == 422, body


def test_server_controlled_fields_cannot_be_sent(api, auth, world) -> None:
    base = {"account_id": str(world.ids["A1"]), "title": "X"}
    for extra in (
        {"status": "active"},
        {"number": 99},
        {"tenant_id": str(world.users["beta.admin"].tenant_id)},
        {"terminated_at": "2027-01-01T00:00:00Z"},
        {"created_by_user_id": str(world.users["alpha.admin"].id)},
        {"renewal_reminded_at": "2027-01-01T00:00:00Z"},
    ):
        response = api.post(CONTRACTS, json={**base, **extra}, headers=auth("alpha.agent1"))
        assert response.status_code == 422, extra


def test_unknown_contract_ids_and_malformed_ids(api, auth, world) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    assert api.get(f"{CONTRACTS}/{missing}", headers=auth("alpha.admin")).status_code == 404
    assert api.get(f"{CONTRACTS}/not-a-uuid", headers=auth("alpha.admin")).status_code == 422


# === Who may do what ==============================================================================


def test_support_and_customers_have_no_access(api, auth, world) -> None:
    contract = new_contract(api, auth, world)
    for user in ("alpha.support", "alpha.customer"):
        assert api.get(CONTRACTS, headers=auth(user)).status_code == 403
        assert api.get(f"{CONTRACTS}/{contract['id']}", headers=auth(user)).status_code == 403
        body = {"account_id": str(world.ids["A1"]), "title": "No"}
        assert api.post(CONTRACTS, json=body, headers=auth(user)).status_code == 403


def test_agents_see_only_their_own_accounts_and_managers_see_all(api, auth, world) -> None:
    mine = new_contract(api, auth, world, user="alpha.agent1", account="A1")
    theirs = new_contract(api, auth, world, user="alpha.manager", account="A2", title="For A2")

    seen = ok(api.get(CONTRACTS, headers=auth("alpha.agent1")))
    assert [c["id"] for c in seen["items"]] == [mine["id"]]
    assert api.get(f"{CONTRACTS}/{theirs['id']}", headers=auth("alpha.agent1")).status_code == 404
    everyone = ok(api.get(CONTRACTS, headers=auth("alpha.manager")))
    assert {c["id"] for c in everyone["items"]} == {mine["id"], theirs["id"]}


def test_an_account_owner_sees_contracts_a_manager_made_on_their_account(api, auth, world) -> None:
    contract = new_contract(
        api,
        auth,
        world,
        user="alpha.manager",
        account="A1",
        owner_id=str(world.users["alpha.manager"].id),
    )
    assert api.get(f"{CONTRACTS}/{contract['id']}", headers=auth("alpha.agent1")).status_code == 200
    # The account owner also has write access to contracts on their own account.
    changed = api.patch(
        f"{CONTRACTS}/{contract['id']}",
        json={"version": 1, "title": "Mine now"},
        headers=auth("alpha.agent1"),
    )
    assert changed.status_code == 200


def test_an_agent_cannot_create_on_someone_elses_account(api, auth, world) -> None:
    body = {"account_id": str(world.ids["A2"]), "title": "Not mine"}
    response = api.post(CONTRACTS, json=body, headers=auth("alpha.agent1"))
    assert code_of(response) == (404, "related_not_found")
    assert api.post(CONTRACTS, json=body, headers=auth("alpha.manager")).status_code == 201


def test_another_organisation_sees_nothing_and_cannot_use_our_records(api, auth, world) -> None:
    contract = new_contract(api, auth, world)
    assert ok(api.get(CONTRACTS, headers=auth("beta.admin")))["items"] == []
    for action in ("history",):
        url = f"{CONTRACTS}/{contract['id']}/{action}"
        assert api.get(url, headers=auth("beta.admin")).status_code == 404
    assert api.get(f"{CONTRACTS}/{contract['id']}", headers=auth("beta.admin")).status_code == 404
    other = {"account_id": str(world.ids["A1"]), "title": "Cross-tenant"}
    assert code_of(api.post(CONTRACTS, json=other, headers=auth("beta.admin"))) == (
        404,
        "related_not_found",
    )
    assert api.patch(
        f"{CONTRACTS}/{contract['id']}",
        json={"version": 1, "title": "Hijack"},
        headers=auth("beta.admin"),
    ).status_code in (403, 404)
    assert step(api, auth, "beta.admin", contract, "activate").status_code in (403, 404)


# === ID tampering =================================================================================


def test_linked_records_must_be_visible_and_belong_to_the_same_account(api, auth, world) -> None:
    body = {"account_id": str(world.ids["A1"]), "title": "Links"}
    wrong_contact = api.post(
        CONTRACTS, json={**body, "contact_id": str(world.ids["C2"])}, headers=auth("alpha.manager")
    )
    assert code_of(wrong_contact) == (422, "invalid_contract")
    wrong_deal = api.post(
        CONTRACTS,
        json={**body, "opportunity_id": str(world.ids["O2"])},
        headers=auth("alpha.manager"),
    )
    assert code_of(wrong_deal) == (422, "invalid_contract")
    foreign = "00000000-0000-4000-8000-000000000000"
    for field in ("contact_id", "opportunity_id", "quote_id"):
        response = api.post(CONTRACTS, json={**body, field: foreign}, headers=auth("alpha.manager"))
        assert code_of(response) == (404, "related_not_found"), field

    other_quote = new_quote(api, auth, world, user="alpha.agent2", account="A2")
    wrong_quote = api.post(
        CONTRACTS,
        json={**body, "quote_id": other_quote["id"]},
        headers=auth("alpha.manager"),
    )
    assert code_of(wrong_quote) == (422, "invalid_contract")
    own_quote = new_quote(api, auth, world, user="alpha.agent1", account="A1")
    good = api.post(
        CONTRACTS, json={**body, "quote_id": own_quote["id"]}, headers=auth("alpha.agent1")
    )
    assert ok(good, 201)["quote_id"] == own_quote["id"]

    # An agent's own contact is fine; a contact the agent cannot see is "not found".
    fine = api.post(
        CONTRACTS, json={**body, "contact_id": str(world.ids["C1"])}, headers=auth("alpha.agent1")
    )
    assert fine.status_code == 201


def test_owners_are_checked(api, auth, world) -> None:
    body = {"account_id": str(world.ids["A1"]), "title": "Owner"}
    agent2 = str(world.users["alpha.agent2"].id)
    # An agent may not hand a contract to someone else...
    response = api.post(CONTRACTS, json={**body, "owner_id": agent2}, headers=auth("alpha.agent1"))
    assert response.status_code == 403
    # ...a manager may, but only to an active sales employee of the same organisation.
    assert (
        api.post(
            CONTRACTS, json={**body, "owner_id": agent2}, headers=auth("alpha.manager")
        ).status_code
        == 201
    )
    foreign = str(world.users["beta.admin"].id)
    response = api.post(
        CONTRACTS, json={**body, "owner_id": foreign}, headers=auth("alpha.manager")
    )
    assert code_of(response) == (422, "invalid_contract")
    support = str(world.users["alpha.support"].id)
    response = api.post(
        CONTRACTS, json={**body, "owner_id": support}, headers=auth("alpha.manager")
    )
    assert code_of(response) == (422, "invalid_contract")


# === Editing ======================================================================================


def test_a_draft_can_be_changed_and_lost_updates_are_refused(api, auth, world) -> None:
    draft = new_contract(api, auth, world)
    url = f"{CONTRACTS}/{draft['id']}"
    changed = ok(
        api.patch(
            url,
            json={"version": 1, "title": "Renamed", "total_value": "500.00", "auto_renew": True},
            headers=auth("alpha.agent1"),
        )
    )
    assert (
        changed["title"],
        changed["total_value"],
        changed["auto_renew"],
        changed["version"],
    ) == (
        "Renamed",
        "500.00",
        True,
        2,
    )
    stale = api.patch(url, json={"version": 1, "title": "Late"}, headers=auth("alpha.agent1"))
    assert code_of(stale) == (409, "version_conflict")
    empty = api.patch(url, json={"version": 2}, headers=auth("alpha.agent1"))
    assert empty.status_code == 422
    clash = api.patch(
        url,
        json={"version": 2, "start_date": str(TODAY + timedelta(days=999))},
        headers=auth("alpha.agent1"),
    )
    assert code_of(clash) == (422, "invalid_contract")  # start would be after the existing end


def test_an_active_contract_keeps_its_dates_and_money(api, auth, world) -> None:
    contract = active(api, auth, world)
    url = f"{CONTRACTS}/{contract['id']}"
    for locked in (
        {"end_date": str(TODAY + timedelta(days=400))},
        {"total_value": "1.00"},
        {"currency": "USD"},
    ):
        response = api.patch(
            url, json={"version": contract["version"], **locked}, headers=auth("alpha.manager")
        )
        assert code_of(response) == (409, "contract_state"), locked
    allowed = ok(
        api.patch(
            url,
            json={"version": contract["version"], "terms": "Net 30", "renewal_notice_days": 60},
            headers=auth("alpha.manager"),
        )
    )
    assert allowed["terms"] == "Net 30"
    assert allowed["renewal_date"] == str(TODAY + timedelta(days=365 - 60))


def test_only_managers_move_the_owner(api, auth, world) -> None:
    draft = new_contract(api, auth, world)
    url = f"{CONTRACTS}/{draft['id']}"
    agent2 = str(world.users["alpha.agent2"].id)
    refused = api.patch(url, json={"version": 1, "owner_id": agent2}, headers=auth("alpha.agent1"))
    assert refused.status_code == 403
    moved = ok(
        api.patch(url, json={"version": 1, "owner_id": agent2}, headers=auth("alpha.manager"))
    )
    assert moved["owner_id"] == agent2


# === Activate, terminate, renew ===================================================================


def test_managers_activate_and_agents_cannot(api, auth, world) -> None:
    draft = new_contract(api, auth, world)
    assert step(api, auth, "alpha.agent1", draft, "activate").status_code == 403
    activated = ok(step(api, auth, "alpha.manager", draft, "activate", note="Signed"))
    assert activated["status"] == "active"
    again = step(api, auth, "alpha.manager", activated, "activate")
    assert code_of(again) == (409, "contract_state")
    history = ok(api.get(f"{CONTRACTS}/{draft['id']}/history", headers=auth("alpha.manager")))
    assert [(e["event_type"], e["from_status"], e["to_status"]) for e in history][0] == (
        "status_changed",
        "draft",
        "active",
    )
    assert history[0]["note"] == "Signed" and history[0]["actor_name"] == "alpha.manager"


def test_activation_needs_dates_that_are_not_over(api, auth, world) -> None:
    undated = ok(
        api.post(
            CONTRACTS,
            json={"account_id": str(world.ids["A1"]), "title": "No dates"},
            headers=auth("alpha.manager"),
        ),
        201,
    )
    assert code_of(step(api, auth, "alpha.manager", undated, "activate")) == (
        422,
        "invalid_contract",
    )
    past = new_contract(
        api,
        auth,
        world,
        start_date=str(TODAY - timedelta(days=100)),
        end_date=str(TODAY - timedelta(days=1)),
    )
    assert code_of(step(api, auth, "alpha.manager", past, "activate")) == (422, "invalid_contract")


def test_stale_versions_are_refused_on_steps(api, auth, world) -> None:
    draft = new_contract(api, auth, world)
    stale = api.post(
        f"{CONTRACTS}/{draft['id']}/activate", json={"version": 99}, headers=auth("alpha.manager")
    )
    assert code_of(stale) == (409, "version_conflict")


def test_terminating_needs_a_reason_and_an_active_contract(api, auth, world) -> None:
    draft = new_contract(api, auth, world)
    assert code_of(step(api, auth, "alpha.manager", draft, "terminate", reason="x")) == (
        409,
        "contract_state",
    )
    contract = ok(step(api, auth, "alpha.manager", draft, "activate"))
    assert step(api, auth, "alpha.agent1", contract, "terminate", reason="r").status_code == 403
    assert step(api, auth, "alpha.manager", contract, "terminate").status_code == 422
    assert step(api, auth, "alpha.manager", contract, "terminate", reason="").status_code == 422
    done = ok(step(api, auth, "alpha.manager", contract, "terminate", reason="Customer left"))
    assert done["status"] == "terminated"
    assert done["termination_reason"] == "Customer left" and done["terminated_at"] is not None
    assert code_of(step(api, auth, "alpha.manager", done, "terminate", reason="again")) == (
        409,
        "contract_state",
    )
    # A terminated contract is final: no edits, no renewal.
    edit = api.patch(
        f"{CONTRACTS}/{done['id']}",
        json={"version": done["version"], "title": "Zombie"},
        headers=auth("alpha.manager"),
    )
    assert code_of(edit) == (409, "contract_state")
    assert code_of(step(api, auth, "alpha.manager", done, "renew")) == (409, "contract_state")


def test_renewing_creates_a_linked_draft_and_activating_it_replaces_the_old_contract(
    api, auth, world
) -> None:
    old = active(api, auth, world, renewal_term_months=12)
    assert step(api, auth, "alpha.agent1", old, "renew").status_code == 403

    renewal = ok(step(api, auth, "alpha.manager", old, "renew", note="Next year"), 201)
    assert renewal["status"] == "draft" and renewal["label"] == "CT-0002"
    assert renewal["renewed_from_id"] == old["id"]
    assert renewal["start_date"] == str(TODAY + timedelta(days=365 + 1))
    assert (
        renewal["total_value"] == old["total_value"] and renewal["account_id"] == old["account_id"]
    )
    first = ok(api.get(f"{CONTRACTS}/{old['id']}", headers=auth("alpha.manager")))
    assert first["status"] == "active" and first["renewed_to_id"] == renewal["id"]

    again = step(api, auth, "alpha.manager", first, "renew")
    assert code_of(again) == (409, "contract_state")  # one renewal at a time

    ok(step(api, auth, "alpha.manager", renewal, "activate"))
    replaced = ok(api.get(f"{CONTRACTS}/{old['id']}", headers=auth("alpha.manager")))
    assert replaced["status"] == "renewed"
    old_history = ok(api.get(f"{CONTRACTS}/{old['id']}/history", headers=auth("alpha.manager")))
    assert any(e["to_status"] == "renewed" for e in old_history)


def test_a_renewal_may_choose_its_dates_and_value(api, auth, world) -> None:
    old = active(api, auth, world)
    start, end = TODAY + timedelta(days=400), TODAY + timedelta(days=800)
    renewal = ok(
        step(
            api,
            auth,
            "alpha.manager",
            old,
            "renew",
            start_date=str(start),
            end_date=str(end),
            total_value="999.99",
        ),
        201,
    )
    assert (renewal["start_date"], renewal["end_date"], renewal["total_value"]) == (
        str(start),
        str(end),
        "999.99",
    )
    backwards = step(
        api,
        auth,
        "alpha.manager",
        ok(api.get(f"{CONTRACTS}/{old['id']}", headers=auth("alpha.manager"))),
        "renew",
        start_date=str(end),
        end_date=str(start),
    )
    assert backwards.status_code == 422


def test_a_draft_cannot_be_renewed(api, auth, world) -> None:
    draft = new_contract(api, auth, world)
    assert code_of(step(api, auth, "alpha.manager", draft, "renew")) == (409, "contract_state")


# === Notes, filters, audit, events ================================================================


def test_notes_go_to_the_history(api, auth, world) -> None:
    contract = new_contract(api, auth, world)
    url = f"{CONTRACTS}/{contract['id']}/notes"
    assert (
        api.post(
            url, json={"note": "Called the customer"}, headers=auth("alpha.support")
        ).status_code
        == 403
    )
    assert api.post(url, json={"note": ""}, headers=auth("alpha.agent1")).status_code == 422
    ok(api.post(url, json={"note": "Called the customer"}, headers=auth("alpha.agent1")))
    history = ok(api.get(f"{CONTRACTS}/{contract['id']}/history", headers=auth("alpha.agent1")))
    assert history[0]["event_type"] == "note" and history[0]["note"] == "Called the customer"


def test_filters_and_search(api, auth, world) -> None:
    soon = active(api, auth, world, title="Ends soon", end_date=str(TODAY + timedelta(days=20)))
    later = active(api, auth, world, title="Ends later", end_date=str(TODAY + timedelta(days=200)))
    draft = new_contract(api, auth, world, title="Still a draft", account="A1")
    other = new_contract(
        api, auth, world, user="alpha.manager", account="A2", title="Other account"
    )

    def get(**params: Any) -> list[str]:
        page = ok(api.get(CONTRACTS, params=params, headers=auth("alpha.manager")))
        return [c["id"] for c in page["items"]]

    assert set(get(status="active")) == {soon["id"], later["id"]}
    assert set(get(status=["draft", "active"])) == {
        soon["id"],
        later["id"],
        draft["id"],
        other["id"],
    }
    assert get(ending_within_days=30) == [soon["id"]]
    assert get(ending_within_days=0) == []
    assert get(account_id=str(world.ids["A2"])) == [other["id"]]
    assert get(owner_id=str(world.users["alpha.manager"].id)) == [other["id"]]
    assert get(q="soon") == [soon["id"]]
    assert get(q="CT-0001") == [soon["id"]]
    assert get(q="%") == []  # a wildcard is not a wildcard
    assert (
        api.get(CONTRACTS, params={"status": "bogus"}, headers=auth("alpha.manager")).status_code
        == 422
    )
    assert api.get(CONTRACTS, params={"limit": 0}, headers=auth("alpha.manager")).status_code == 422
    page = ok(api.get(CONTRACTS, params={"limit": 1, "offset": 1}, headers=auth("alpha.manager")))
    assert page["total"] == 4 and len(page["items"]) == 1


def test_status_changes_are_audited_and_published(api, auth, world, db_session) -> None:
    contract = new_contract(api, auth, world)
    activated = ok(step(api, auth, "alpha.manager", contract, "activate"))
    ok(step(api, auth, "alpha.manager", activated, "terminate", reason="Stopped"))
    actions = set(
        db_session.scalars(
            select(AuditLog.action).where(
                AuditLog.entity_type == "contract", AuditLog.entity_id == uuid_of(contract)
            )
        )
    )
    assert {"contract.created", "contract.active", "contract.terminated"} <= actions
    kinds = set(
        db_session.scalars(select(OutboxJob.kind).where(OutboxJob.kind.like("event.contract.%")))
    )
    assert kinds == {"event.contract.activated", "event.contract.terminated"}


def uuid_of(contract: Any):
    import uuid

    return uuid.UUID(contract["id"])


# === The service refuses on its own too (second layer behind the router) ==========================


def test_the_service_itself_refuses_manager_steps_to_an_agent(api, auth, world, db_session) -> None:
    """Defence in depth: even if a route forgot its permission check, the service stops an
    agent from activating, terminating or renewing."""
    import pytest

    from app.core.auth.principal import Principal
    from app.core.auth.rbac import Role, permissions_for
    from app.core.db import bind_tenant
    from app.core.errors import ForbiddenError
    from app.modules.contracts import service
    from app.modules.contracts.schemas import RenewInput
    from tests.auth_helpers import TEST_ISSUER

    draft = new_contract(api, auth, world)
    agent = world.users["alpha.agent1"]
    principal = Principal(
        subject=agent.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.SALES_AGENT}),
        permissions=permissions_for(frozenset({Role.SALES_AGENT})),
        user_id=agent.id,
        tenant_id=agent.tenant_id,
    )
    bind_tenant(db_session, agent.tenant_id)
    contract_id = __import__("uuid").UUID(draft["id"])
    with pytest.raises(ForbiddenError):
        service.activate(db_session, principal, contract_id, version=1, note=None)
    with pytest.raises(ForbiddenError):
        service.terminate(db_session, principal, contract_id, version=1, reason="x")
    with pytest.raises(ForbiddenError):
        service.renew(db_session, principal, contract_id, RenewInput(version=1))
