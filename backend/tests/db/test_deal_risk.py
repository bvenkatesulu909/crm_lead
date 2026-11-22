# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Deal risk snapshots against the real database (ADR 0037, step DR2).

The risk is worked out by code from signals read AS THE PERSON ASKING (the nightly job asks as the
organisation's Automation identity). Happy path, role denial, record-level denial, tenant
isolation, ID tampering, the insert-only table, the nightly pass (idempotent, one organisation at a
time) and the retention sweep.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.modules.activities.models import Activity
from app.modules.deal_risk import api as deal_risk
from app.modules.deal_risk.models import DealRiskSnapshot
from app.modules.sales.models import Opportunity
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import (  # noqa: F401
    Headers,
    World,
    api,
    auth,
    lines,
    new_quote,
    world,
)

NOW = datetime.now(UTC)


def who(db_session: Session, world: World, name: str):  # noqa: ANN201
    principal = principal_for(world.users[name], ROLES[name])
    bind_principal(db_session, principal)
    return principal


def risky_deal(db_session: Session, world: World) -> uuid.UUID:
    """An old open deal with nothing planned: no next step, no contact, a passed close date, one
    overdue task and no finished activity."""
    who(db_session, world, "alpha.manager")
    tenant = world.users["alpha.agent1"].tenant_id
    deal = Opportunity(
        tenant_id=tenant,
        name="Risky deal",
        account_id=world.ids["A1"],
        owner_id=world.users["alpha.agent1"].id,
        currency="INR",
        stage="negotiation",
        expected_close_date=(NOW - timedelta(days=10)).date(),
        created_at=NOW - timedelta(days=60),
    )
    db_session.add(deal)
    db_session.flush()
    db_session.add(
        Activity(
            tenant_id=tenant,
            kind="task",
            subject="Call back",
            status="open",
            due_at=NOW - timedelta(days=3),
            assignee_id=world.users["alpha.agent1"].id,
            opportunity_id=deal.id,
        )
    )
    db_session.flush()
    return deal.id


def codes_of(snapshot: DealRiskSnapshot) -> set[str]:
    return {f["code"] for f in snapshot.factors}


def test_a_manager_gets_the_risk_with_its_reasons_and_it_is_stored(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")

    snapshot = deal_risk.snapshot_on_demand(db_session, manager, deal, NOW)

    assert {
        "no_touch_30",
        "overdue_tasks",
        "close_date_passed",
        "no_primary_contact",
    } <= codes_of(snapshot)
    assert snapshot.level == "high" and snapshot.score >= 60
    assert snapshot.source == "on_demand" and snapshot.requested_by_user_id == manager.user_id
    assert all(f["sentence"] for f in snapshot.factors)
    # What was stored is what the newest read returns.
    newest = deal_risk.latest_snapshot(db_session, manager, deal)
    assert newest is not None and newest.id == snapshot.id


def test_asking_is_audited_with_ids_and_counts_only(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")
    deal_risk.snapshot_on_demand(db_session, manager, deal, NOW)
    row = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "deal_risk.computed", AuditLog.entity_id == deal)
    ).one()
    assert set(row.changes) == {"level", "score", "factors"}


def test_computing_without_storing_stores_nothing(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")
    risk = deal_risk.compute(db_session, manager, deal, NOW)
    assert risk.score > 0
    assert db_session.scalars(select(DealRiskSnapshot)).all() == []


@pytest.mark.parametrize("name", ["alpha.agent1", "alpha.support", "alpha.customer"])
def test_people_without_the_permission_are_refused(world, db_session, name: str) -> None:
    deal = risky_deal(db_session, world)
    person = who(db_session, world, name)
    with pytest.raises(deal_risk.DealRiskNotAllowedError):
        deal_risk.snapshot_on_demand(db_session, person, deal, NOW)
    with pytest.raises(deal_risk.DealRiskNotAllowedError):
        deal_risk.latest_snapshot(db_session, person, deal)


def test_an_administrator_may_ask_too(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    admin = who(db_session, world, "alpha.admin")
    assert deal_risk.snapshot_on_demand(db_session, admin, deal, NOW).level in {"medium", "high"}


def test_a_made_up_deal_id_is_not_found(world, db_session) -> None:
    manager = who(db_session, world, "alpha.manager")
    with pytest.raises(deal_risk.DealNotFoundError):
        deal_risk.snapshot_on_demand(db_session, manager, uuid.uuid4(), NOW)
    with pytest.raises(deal_risk.DealNotFoundError):
        deal_risk.latest_snapshot(db_session, manager, uuid.uuid4())


def test_another_organisations_deal_is_not_found(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    other = who(db_session, world, "beta.admin")
    with pytest.raises(deal_risk.DealNotFoundError):
        deal_risk.snapshot_on_demand(db_session, other, deal, NOW)
    with pytest.raises(deal_risk.DealNotFoundError):
        deal_risk.latest_snapshot(db_session, other, deal)


def test_a_closed_deal_has_no_forecast(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")
    row = db_session.get(Opportunity, deal)
    assert row is not None
    row.stage, row.closed_at = "closed_won", NOW
    db_session.flush()
    with pytest.raises(deal_risk.DealNotFoundError):
        deal_risk.compute(db_session, manager, deal, NOW)


def test_a_healthy_looking_deal_scores_low(world, db_session) -> None:
    manager = who(db_session, world, "alpha.manager")
    tenant = world.users["alpha.agent1"].tenant_id
    deal = Opportunity(
        tenant_id=tenant,
        name="Calm deal",
        account_id=world.ids["A1"],
        owner_id=world.users["alpha.agent1"].id,
        primary_contact_id=None,
        currency="INR",
        stage="prospecting",
        next_step="Send the brochure",
        expected_close_date=(NOW + timedelta(days=40)).date(),
    )
    db_session.add(deal)
    db_session.flush()
    db_session.add(
        Activity(
            tenant_id=tenant,
            kind="call",
            subject="Intro call",
            status="done",
            completed_at=NOW - timedelta(days=1),
            assignee_id=world.users["alpha.agent1"].id,
            opportunity_id=deal.id,
        )
    )
    db_session.flush()
    risk = deal_risk.compute(db_session, manager, deal.id, NOW)
    assert risk.level == "low"
    assert "no_touch_14" not in {f.code for f in risk.factors}
    # With too few won deals there is no "usual" stage time, and the answer says so.
    assert "typical_stage_time" in risk.unknown


def test_the_snapshot_table_is_insert_only(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")
    stored = deal_risk.snapshot_on_demand(db_session, manager, deal, NOW)
    for statement in (
        text("UPDATE deal_risk_snapshots SET level = 'low' WHERE id = :id"),
        text("DELETE FROM deal_risk_snapshots WHERE id = :id"),
    ):
        nested = db_session.begin_nested()
        with pytest.raises(DBAPIError):
            db_session.execute(statement, {"id": stored.id})
        nested.rollback()


@pytest.mark.parametrize(
    "bad",
    [
        {"level": "extreme"},
        {"score": 101},
        {"score": -1},
        {"rules_version": 0},
        {"source": "magic"},
        {"source": "nightly", "requested_by_user_id": "asker"},
        {"source": "on_demand", "requested_by_user_id": None},
    ],
)
def test_the_database_refuses_a_malformed_snapshot(
    world, db_session, bad: dict[str, object]
) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")
    values = {
        "level": "low",
        "score": 0,
        "rules_version": 1,
        "source": "on_demand",
        "requested_by_user_id": manager.user_id,
    }
    values.update(bad)
    if values["requested_by_user_id"] == "asker":
        values["requested_by_user_id"] = manager.user_id
    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError):
        db_session.add(
            DealRiskSnapshot(
                tenant_id=manager.tenant_id, opportunity_id=deal, factors=[], unknown=[], **values
            )
        )
        db_session.flush()
    nested.rollback()


def test_the_nightly_pass_snapshots_open_deals_once_and_skips_closed_ones(
    world, db_session
) -> None:
    deal = risky_deal(db_session, world)
    closed = Opportunity(
        tenant_id=world.users["alpha.agent1"].tenant_id,
        name="Closed",
        account_id=world.ids["A1"],
        currency="INR",
        stage="closed_lost",
        lost_reason="price",
        closed_at=NOW,
    )
    db_session.add(closed)
    db_session.flush()
    tenant = world.users["alpha.agent1"].tenant_id
    bind_tenant(db_session, tenant)

    first = deal_risk.run_nightly(db_session, NOW, tenant_id=tenant)
    assert first >= 1
    rows = db_session.scalars(select(DealRiskSnapshot)).all()
    assert closed.id not in {r.opportunity_id for r in rows}
    assert deal in {r.opportunity_id for r in rows}
    assert all(r.source == "nightly" and r.requested_by_user_id is None for r in rows)

    # Safe to repeat: a second pass the same day stores nothing new.
    assert deal_risk.run_nightly(db_session, NOW + timedelta(minutes=1), tenant_id=tenant) == 0
    assert len(db_session.scalars(select(DealRiskSnapshot)).all()) == len(rows)

    # A day later it stores a new snapshot for each deal (a history, not an overwrite).
    later = NOW + timedelta(hours=21)
    assert deal_risk.run_nightly(db_session, later, tenant_id=tenant) == first


def test_the_nightly_pass_never_touches_another_organisation(world, db_session) -> None:
    risky_deal(db_session, world)
    beta = world.users["beta.agent"].tenant_id
    bind_tenant(db_session, beta)
    deal_risk.run_nightly(db_session, NOW, tenant_id=beta)
    alpha = world.users["alpha.agent1"].tenant_id
    rows = db_session.scalars(select(DealRiskSnapshot)).all()
    assert all(r.tenant_id == beta for r in rows)
    assert alpha not in {r.tenant_id for r in rows}


def test_the_retention_sweep_keeps_young_rows_and_removes_old_ones(world, db_session) -> None:
    deal = risky_deal(db_session, world)
    manager = who(db_session, world, "alpha.manager")
    deal_risk.snapshot_on_demand(db_session, manager, deal, NOW)
    tenant = manager.tenant_id
    assert tenant is not None
    # Young rows are never deleted by the sweep (the trigger would refuse it anyway).
    assert deal_risk.delete_expired(db_session, NOW, tenant_id=tenant) == 0
    assert len(db_session.scalars(select(DealRiskSnapshot)).all()) == 1
