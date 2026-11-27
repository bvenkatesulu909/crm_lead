"""Reservation tables against real PostgreSQL (ADR 0040, RP2): what the DATABASE refuses.

Setup rows are built as crm_owner (committed_world); every assertion runs as crm_app with the
tenant bound, so row-level security and the revoked privileges apply.
"""

# ruff: noqa: F811 - the fixtures are imported and used by name

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.reservations.models import ReservationSettings
from app.modules.sales.models import Opportunity
from app.modules.units.models import PropertyProject, PropertyUnit
from tests.db.test_invoices_api import World, world  # noqa: F401 - fixture used by name

REFUSED = (IntegrityError, DBAPIError, ProgrammingError)


@dataclass
class Side:
    tenant: uuid.UUID
    user: uuid.UUID
    deal: uuid.UUID
    unit: uuid.UUID
    unit2: uuid.UUID


@pytest.fixture
def sides(world: World, committed_world: Session) -> dict[str, Side]:
    out: dict[str, Side] = {}
    for slug, user, account in [("alpha", "alpha.manager", "A1"), ("beta", "beta.admin", "B1")]:
        u = world.users[user]
        deal = Opportunity(
            tenant_id=u.tenant_id, name=f"{slug} flat", account_id=world.accounts[account],
            owner_id=u.id, currency="INR", amount=Decimal("4500000"),
        )  # fmt: skip
        project = PropertyProject(tenant_id=u.tenant_id, name=f"{slug} Green Valley")
        committed_world.add_all([deal, project])
        committed_world.flush()
        units = [
            PropertyUnit(
                tenant_id=u.tenant_id,
                project_id=project.id,
                unit_code=code,
                unit_type="apartment",
                price=Decimal("4500000"),
            )  # fmt: skip
            for code in ("A-101", "A-102")
        ]
        committed_world.add_all(units)
        committed_world.add(
            ReservationSettings(
                tenant_id=u.tenant_id, version_no=1, amount_mode="percent", percent=Decimal("2"),
                min_amount=Decimal("50000"), max_amount=Decimal("500000"),
                free_cancel_hours=48, kept_percent=Decimal("10"), created_by_user_id=u.id,
            )
        )  # fmt: skip
        committed_world.flush()
        out[slug] = Side(u.tenant_id, u.id, deal.id, units[0].id, units[1].id)
    committed_world.commit()
    return out


def reserve(db: Session, s: Side, *, unit: uuid.UUID | None = None, **over: Any) -> uuid.UUID:
    bind_tenant(db, s.tenant)
    now = datetime.now(UTC)
    row = {
        "tenant_id": s.tenant,
        "unit_id": unit or s.unit,
        "opportunity_id": s.deal,
        "settings_version": 1,
        "amount": Decimal("90000"),
        "status": "pending_payment",
        "payment_due_at": now + timedelta(hours=24),
        "created_by_user_id": s.user,
        **over,
    }
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    new_id: uuid.UUID = db.execute(
        text(f"insert into reservations ({cols}) values ({marks}) returning id"),  # noqa: S608
        row,
    ).scalar_one()
    return new_id


def refused(db: Session, sql: str, params: dict[str, Any]) -> None:
    with pytest.raises(REFUSED):
        with db.begin_nested():
            db.execute(text(sql), params)


def pay(db: Session, rid: uuid.UUID) -> None:
    now = datetime.now(UTC)
    db.execute(
        text(
            "update reservations set status = 'held', paid_at = :p, held_until = :h where id = :i"
        ),
        {"p": now, "h": now + timedelta(days=7), "i": rid},
    )


# --- one buyer per unit ---------------------------------------------------------------------


def test_a_unit_can_be_reserved(db_session, sides) -> None:
    rid = reserve(db_session, sides["alpha"])
    status = db_session.scalar(text("select status from reservations where id = :i"), {"i": rid})
    assert status == "pending_payment"


def test_a_second_active_reservation_on_the_same_unit_is_refused(db_session, sides) -> None:
    alpha = sides["alpha"]
    reserve(db_session, alpha)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            reserve(db_session, alpha)


def test_a_held_unit_also_blocks_a_second_buyer(db_session, sides) -> None:
    alpha = sides["alpha"]
    pay(db_session, reserve(db_session, alpha))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            reserve(db_session, alpha)


def test_once_the_first_has_ended_the_unit_can_be_reserved_again(db_session, sides) -> None:
    alpha = sides["alpha"]
    first = reserve(db_session, alpha)
    db_session.execute(
        text("update reservations set status = 'expired' where id = :i"), {"i": first}
    )
    assert reserve(db_session, alpha) != first


def test_another_unit_is_not_blocked(db_session, sides) -> None:
    alpha = sides["alpha"]
    reserve(db_session, alpha)
    assert reserve(db_session, alpha, unit=alpha.unit2)


# --- status changes and fixed terms ---------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "bad"),
    [
        ("pending_payment", "converted"),
        ("pending_payment", "refunded"),
        ("held", "pending_payment"),
        ("held", "expired"),
        ("held", "cancelled"),
    ],
)
def test_the_database_refuses_a_status_change_the_rules_do_not_allow(
    db_session, sides, start: str, bad: str
) -> None:
    rid = reserve(db_session, sides["alpha"])
    if start == "held":
        pay(db_session, rid)
    refused(db_session, "update reservations set status = :s where id = :i", {"s": bad, "i": rid})


def test_the_allowed_path_to_a_refund_works(db_session, sides) -> None:
    rid = reserve(db_session, sides["alpha"])
    pay(db_session, rid)
    db_session.execute(
        text(
            "update reservations set status = 'refund_due', refund_due_amount = 90000,"
            " refund_reason = 'seller_cancelled' where id = :i"
        ),
        {"i": rid},
    )
    db_session.execute(
        text(
            "update reservations set status = 'refunded', refund_reference = 'rfnd_Abc123XYZ'"
            " where id = :i"
        ),
        {"i": rid},
    )
    assert db_session.scalar(text("select status from reservations where id = :i"), {"i": rid}) == (
        "refunded"
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("amount", Decimal("1")),
        ("unit_id", None),
        ("opportunity_id", None),
        ("settings_version", 2),
        ("payment_due_at", None),
    ],
)
def test_the_terms_of_a_reservation_cannot_be_changed(db_session, sides, column, value) -> None:
    alpha = sides["alpha"]
    rid = reserve(db_session, alpha)
    if column == "unit_id":
        value = alpha.unit2
    if column == "opportunity_id":
        value = uuid.uuid4()
    if column == "payment_due_at":
        value = datetime.now(UTC) + timedelta(days=30)
    refused(
        db_session,
        f"update reservations set {column} = :v where id = :i",  # noqa: S608 - fixed list above
        {"v": value, "i": rid},
    )


def test_a_reservation_cannot_be_deleted(db_session, sides) -> None:
    rid = reserve(db_session, sides["alpha"])
    refused(db_session, "delete from reservations where id = :i", {"i": rid})


# --- impossible rows ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "over",
    [
        {"amount": Decimal("0")},
        {"status": "gone"},
        {"status": "held"},  # held without being paid
        {"status": "refund_due", "paid_at": datetime.now(UTC)},  # no amount or reason
        {"status": "refunded"},  # no reference
        {"refund_reference": "pay_12345678"},
        {"refund_due_amount": Decimal("90000.01")},
        {"refund_reason": "felt_like_it"},
        {"payment_due_at": datetime.now(UTC) - timedelta(hours=1)},
        {"settings_version": 9},  # no such rules version
    ],
)
def test_the_database_refuses_impossible_reservations(db_session, sides, over) -> None:
    with pytest.raises(REFUSED):
        with db_session.begin_nested():
            reserve(db_session, sides["alpha"], **over)


@pytest.mark.parametrize(
    "over",
    [
        {"amount_mode": "weekly"},
        {"amount_mode": "fixed"},  # fixed without an amount (percent still set)
        {"percent": Decimal("0")},
        {"percent": Decimal("100.5")},
        {"min_amount": Decimal("0")},
        {"min_amount": Decimal("600000")},  # above the maximum
        {"free_cancel_hours": 721},
        {"kept_percent": Decimal("101")},
    ],
)
def test_the_database_refuses_impossible_settings(db_session, sides, over) -> None:
    alpha = sides["alpha"]
    bind_tenant(db_session, alpha.tenant)
    row = {
        "tenant_id": alpha.tenant, "version_no": 2, "amount_mode": "percent", "fixed_amount": None,
        "percent": Decimal("2"), "min_amount": Decimal("50000"), "max_amount": Decimal("500000"),
        "free_cancel_hours": 48, "kept_percent": Decimal("10"), "created_by_user_id": alpha.user,
        **over,
    }  # fmt: skip
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    refused(
        db_session,
        f"insert into reservation_settings ({cols}) values ({marks})",  # noqa: S608
        row,
    )


# --- insert-only tables ---------------------------------------------------------------------


def test_settings_versions_cannot_be_changed_or_deleted(db_session, sides) -> None:
    bind_tenant(db_session, sides["alpha"].tenant)
    refused(db_session, "update reservation_settings set kept_percent = 50", {})
    refused(db_session, "delete from reservation_settings", {})


def test_the_history_cannot_be_changed_or_deleted(db_session, sides) -> None:
    alpha = sides["alpha"]
    rid = reserve(db_session, alpha)
    db_session.execute(
        text(
            "insert into reservation_events (tenant_id, reservation_id, to_status, actor_user_id)"
            " values (:t, :r, 'pending_payment', :u)"
        ),
        {"t": alpha.tenant, "r": rid, "u": alpha.user},
    )
    refused(db_session, "update reservation_events set reason = 'x'", {})
    refused(db_session, "delete from reservation_events", {})


# --- tenant isolation ---------------------------------------------------------------------


def test_another_organisation_sees_nothing(db_session, sides) -> None:
    reserve(db_session, sides["alpha"])
    bind_tenant(db_session, sides["beta"].tenant)
    for table in ("reservations", "reservation_settings"):
        rows = db_session.scalar(text(f"select count(*) from {table}"))  # noqa: S608
        assert rows == 1 if table == "reservation_settings" else rows == 0


def test_a_reservation_cannot_point_at_another_organisations_unit_or_deal(
    db_session, sides
) -> None:
    alpha, beta = sides["alpha"], sides["beta"]
    with pytest.raises(REFUSED):
        with db_session.begin_nested():
            reserve(db_session, beta, unit=alpha.unit)
    with pytest.raises(REFUSED):
        with db_session.begin_nested():
            reserve(db_session, beta, opportunity_id=alpha.deal)


def test_a_row_for_another_tenant_cannot_be_written(db_session, sides) -> None:
    alpha, beta = sides["alpha"], sides["beta"]
    bind_tenant(db_session, alpha.tenant)  # signed in as alpha, writing a beta row
    refused(
        db_session,
        "insert into reservations (tenant_id, unit_id, opportunity_id, settings_version, amount,"
        " payment_due_at, created_by_user_id)"
        " values (:t, :u, :o, 1, 1, now() + interval '1 day', :c)",
        {"t": beta.tenant, "u": beta.unit, "o": beta.deal, "c": beta.user},
    )
