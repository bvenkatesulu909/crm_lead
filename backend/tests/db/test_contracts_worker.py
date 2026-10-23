# ruff: noqa: F811 - pytest fixtures imported from other test modules are used as parameters
"""Contracts, step C3: expiry sweep, auto-renew drafts and renewal reminders, run by the worker.

People and fixtures come from test_quotes_api.py and test_notifications.py (the worker runs in
the test with an in-memory mailer). Contract dates are moved with plain SQL, because the API
refuses to activate a contract that has already ended.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.core.db import bind_tenant
from app.core.outbox import OutboxJob
from app.modules.contracts import api as contracts_api
from app.modules.contracts.models import Contract
from tests.db.test_contracts_api import CONTRACTS, active, new_contract
from tests.db.test_contracts_api import step as contract_step
from tests.db.test_notifications import mailer, titles, worker  # noqa: F401
from tests.db.test_quotes_api import api, auth, ok, world  # noqa: F401

TODAY = datetime.now(UTC).date()


def set_dates(db_session, world, contract: Any, *, start: date, end: date, tenant="alpha.admin"):
    bind_tenant(db_session, world.users[tenant].tenant_id)
    db_session.execute(
        update(Contract)
        .where(Contract.id == uuid.UUID(contract["id"]))
        .values(start_date=start, end_date=end)
    )
    db_session.flush()


def read(api, auth, contract: Any, user="alpha.manager") -> Any:
    return ok(api.get(f"{CONTRACTS}/{contract['id']}", headers=auth(user)))


def history(api, auth, contract: Any, user="alpha.manager") -> Any:
    return ok(api.get(f"{CONTRACTS}/{contract['id']}/history", headers=auth(user)))


def ended_yesterday(db_session, world, contract: Any) -> None:
    set_dates(
        db_session,
        world,
        contract,
        start=TODAY - timedelta(days=400),
        end=TODAY - timedelta(days=1),
    )


# === Expiry =======================================================================================


def test_a_contract_past_its_end_date_expires_and_its_owner_is_told(
    api, auth, world, db_session, worker
) -> None:
    ended = active(api, auth, world, title="Ended")
    running = active(api, auth, world, title="Still running")
    draft = new_contract(
        api,
        auth,
        world,
        title="A late draft",
        start_date=str(TODAY - timedelta(days=50)),
        end_date=str(TODAY - timedelta(days=5)),
    )
    ended_yesterday(db_session, world, ended)

    worker()

    assert read(api, auth, ended)["status"] == "expired"
    assert read(api, auth, running)["status"] == "active"
    assert read(api, auth, draft)["status"] == "draft"  # only ACTIVE contracts expire
    entry = history(api, auth, ended)[0]
    assert (entry["event_type"], entry["from_status"], entry["to_status"]) == (
        "expired",
        "active",
        "expired",
    )
    assert entry["actor_name"] is None  # done by the system, not by a person
    assert titles(api, auth, "alpha.agent1") == ["Contract expired: CT-0001: Ended"]
    assert titles(api, auth, "alpha.support") == []  # not their contract, not their business

    worker()  # repeating changes nothing
    assert titles(api, auth, "alpha.agent1") == ["Contract expired: CT-0001: Ended"]
    assert len(history(api, auth, ended)) == 3  # created, activated, expired - nothing more


def test_expired_contracts_cannot_be_edited_but_can_still_be_renewed(
    api, auth, world, db_session, worker
) -> None:
    contract = active(api, auth, world)
    ended_yesterday(db_session, world, contract)
    worker()
    expired = read(api, auth, contract)
    assert expired["status"] == "expired"
    edit = api.patch(
        f"{CONTRACTS}/{contract['id']}",
        json={"version": expired["version"], "title": "Zombie"},
        headers=auth("alpha.manager"),
    )
    assert edit.status_code == 409
    renewal = ok(contract_step(api, auth, "alpha.manager", expired, "renew"), 201)
    assert renewal["renewed_from_id"] == contract["id"]


# === Auto-renew ===================================================================================


def test_auto_renew_prepares_one_draft_renewal_for_a_manager_to_activate(
    api, auth, world, db_session, worker
) -> None:
    auto = active(api, auth, world, title="Auto", auto_renew=True, renewal_term_months=12)
    manual = active(api, auth, world, title="Manual")
    ended_yesterday(db_session, world, auto)
    ended_yesterday(db_session, world, manual)

    worker()
    worker()  # a second run must not prepare a second renewal

    old = read(api, auth, auto)
    assert old["status"] == "expired" and old["renewed_to_id"] is not None
    renewal = read(api, auth, {"id": old["renewed_to_id"]})
    assert renewal["status"] == "draft"  # never activated behind a manager's back
    assert renewal["renewed_from_id"] == auto["id"]
    assert renewal["start_date"] == str(TODAY)  # the day after the old end (yesterday)
    assert renewal["total_value"] == auto["total_value"]
    created = history(api, auth, {"id": old["renewed_to_id"]})[0]
    assert created["event_type"] == "created" and created["actor_name"] is None
    assert read(api, auth, manual)["renewed_to_id"] is None  # no auto-renew, no renewal
    page = ok(api.get(CONTRACTS, headers=auth("alpha.manager")))
    assert page["total"] == 3  # auto, its renewal, manual

    # The manager reviews and activates it: the expired contract becomes "renewed".
    ok(contract_step(api, auth, "alpha.manager", renewal, "activate"))
    assert read(api, auth, auto)["status"] == "renewed"


# === Renewal reminders ============================================================================


def test_the_renewal_reminder_goes_out_once_when_the_notice_period_starts(
    api, auth, world, db_session, worker, mailer
) -> None:
    due = active(api, auth, world, title="Due", end_date=str(TODAY + timedelta(days=20)))
    later = active(api, auth, world, title="Later", end_date=str(TODAY + timedelta(days=60)))
    on_the_day = active(
        api,
        auth,
        world,
        title="Zero notice",
        end_date=str(TODAY + timedelta(days=5)),
        renewal_notice_days=0,
    )

    worker()

    assert titles(api, auth, "alpha.agent1") == ["Renewal due: CT-0001: Due"]
    assert read(api, auth, due)["renewal_reminded_at"] is not None
    assert read(api, auth, later)["renewal_reminded_at"] is None  # 40 days before its date
    assert read(api, auth, on_the_day)["renewal_reminded_at"] is None
    reminder = history(api, auth, due)[0]
    assert reminder["event_type"] == "renewal_reminder" and reminder["actor_name"] is None
    assert [m.subject for m in mailer.sent] == ["Renewal due: CT-0001: Due"]  # e-mail by default

    worker()  # nothing new: one reminder per renewal date
    assert titles(api, auth, "alpha.agent1") == ["Renewal due: CT-0001: Due"]
    assert len(mailer.sent) == 1
    assert [e["event_type"] for e in history(api, auth, due)].count("renewal_reminder") == 1


def test_changing_the_notice_period_arms_the_reminder_again(api, auth, world, worker) -> None:
    contract = active(api, auth, world, end_date=str(TODAY + timedelta(days=20)))
    worker()
    current = read(api, auth, contract)  # the worker's reminder bumped the version
    assert current["renewal_reminded_at"] is not None

    changed = ok(
        api.patch(
            f"{CONTRACTS}/{contract['id']}",
            json={"version": current["version"], "renewal_notice_days": 90},
            headers=auth("alpha.manager"),
        )
    )
    assert changed["renewal_reminded_at"] is None  # the renewal date moved: remind again
    worker()
    assert len(titles(api, auth, "alpha.agent1")) == 2


def test_a_contract_that_has_already_ended_is_expired_not_reminded(
    api, auth, world, db_session, worker
) -> None:
    contract = active(api, auth, world)
    ended_yesterday(db_session, world, contract)
    worker()
    kinds = {e["event_type"] for e in history(api, auth, contract)}
    assert "expired" in kinds and "renewal_reminder" not in kinds
    assert (
        db_session.scalars(
            select(OutboxJob.kind).where(OutboxJob.kind == "event.contract.renewal_due")
        ).all()
        == []
    )


# === Isolation and repeatability ==================================================================


def test_each_organisation_is_swept_on_its_own(api, auth, world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta_account = "B1"
    draft = new_contract(api, auth, world, user="beta.agent", account=beta_account)
    beta = ok(contract_step(api, auth, "beta.admin", draft, "activate"))
    mine = active(api, auth, world)
    ended_yesterday(db_session, world, mine)
    set_dates(
        db_session,
        world,
        beta,
        start=TODAY - timedelta(days=400),
        end=TODAY - timedelta(days=1),
        tenant="beta.admin",
    )

    bind_tenant(db_session, alpha)
    now = datetime.now(UTC)
    assert contracts_api.run_schedules(db_session, now, tenant_id=alpha) == 1
    assert contracts_api.run_schedules(db_session, now, tenant_id=alpha) == 0  # repeatable

    assert read(api, auth, mine)["status"] == "expired"
    assert read(api, auth, beta, user="beta.admin")["status"] == "active"  # not alpha's business
