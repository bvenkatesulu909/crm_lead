"""Contracts and renewals, step C1: the database layer (migration 0037, docs/contracts.md).

The table rules are enforced by PostgreSQL itself, so these tests go straight to the database
as the restricted crm_app role (the one the API uses). Setup data is built as crm_owner.
"""

# ruff: noqa: F811 - the imported world fixture is used as a test parameter

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant, clear_tenant
from app.modules.contracts.models import Contract, ContractEvent, ContractNumberCounter
from tests.db.test_quotes_api import world  # noqa: F401

TODAY = date(2026, 10, 23)


def _contract(world, **values: Any) -> Contract:
    """A valid draft contract in tenant alpha; tests override single fields to break one rule."""
    base: dict[str, Any] = {
        "tenant_id": world.users["alpha.admin"].tenant_id,
        "number": 1,
        "title": "Support agreement",
        "account_id": world.ids["A1"],
        "owner_id": world.users["alpha.agent1"].id,
    }
    base.update(values)
    return Contract(**base)


def _insert(world, db_session: Session, **values: Any) -> Contract:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    contract = _contract(world, **values)
    db_session.add(contract)
    db_session.flush()
    return contract


def test_a_draft_contract_gets_sensible_defaults(world, db_session) -> None:
    contract = _insert(world, db_session)
    db_session.refresh(contract)
    assert contract.status == "draft"
    assert contract.currency == "EUR"
    assert contract.total_value == Decimal("0.00")
    assert contract.billing_frequency == "annually"
    assert contract.auto_renew is False
    assert contract.renewal_notice_days == 30
    assert contract.version == 1


def test_an_active_contract_with_dates_and_money_is_stored(world, db_session) -> None:
    contract = _insert(
        world,
        db_session,
        status="active",
        start_date=TODAY,
        end_date=TODAY + timedelta(days=365),
        total_value=Decimal("12345.67"),
        auto_renew=True,
        renewal_term_months=12,
    )
    db_session.refresh(contract)
    assert contract.total_value == Decimal("12345.67")  # exact decimal money, no float rounding


@pytest.mark.parametrize(
    "values, rule",
    [
        ({"start_date": TODAY, "end_date": TODAY - timedelta(days=1)}, "dates_in_order"),
        ({"status": "active"}, "dates_when_not_draft"),
        ({"status": "active", "start_date": TODAY}, "dates_when_not_draft"),
        ({"total_value": Decimal("-1")}, "value_not_negative"),
        ({"currency": "eur"}, "currency_iso"),
        ({"currency": "E2R"}, "currency_iso"),
        (
            {"status": "frozen", "start_date": TODAY, "end_date": TODAY + timedelta(days=1)},
            "status_allowed",
        ),
        ({"billing_frequency": "daily"}, "billing_allowed"),
        ({"renewal_notice_days": 400}, "notice_days_range"),
        ({"renewal_notice_days": -1}, "notice_days_range"),
        ({"renewal_term_months": 0}, "renewal_term_range"),
        ({"renewal_term_months": 121}, "renewal_term_range"),
        ({"termination_reason": "No longer needed"}, "reason_only_if_terminated"),
    ],
)
def test_the_database_refuses_impossible_contracts(world, db_session, values, rule) -> None:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    with pytest.raises(IntegrityError, match=rule), db_session.begin_nested():
        db_session.add(_contract(world, **values))
        db_session.flush()


def test_a_terminated_contract_needs_a_reason_and_a_date(world, db_session) -> None:
    dates = {"start_date": TODAY, "end_date": TODAY + timedelta(days=30)}
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    with pytest.raises(IntegrityError, match="terminated_has_date"), db_session.begin_nested():
        db_session.add(_contract(world, status="terminated", termination_reason="Why", **dates))
        db_session.flush()
    with pytest.raises(IntegrityError, match="terminated_has_reason"), db_session.begin_nested():
        db_session.add(_contract(world, status="terminated", terminated_at=text("now()"), **dates))
        db_session.flush()
    ok = _contract(
        world,
        status="terminated",
        termination_reason="Customer left",
        terminated_at=text("now()"),
        **dates,
    )
    db_session.add(ok)
    db_session.flush()


def test_numbers_are_unique_inside_one_organisation(world, db_session) -> None:
    _insert(world, db_session, number=7)
    with pytest.raises(IntegrityError, match="uq_contracts_tenant_id_number"):
        with db_session.begin_nested():
            db_session.add(_contract(world, number=7, title="Duplicate number"))
            db_session.flush()
    # The same number in the OTHER organisation is fine: numbering is per tenant.
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, beta)
    db_session.add(
        Contract(
            tenant_id=beta,
            number=7,
            title="Beta contract",
            account_id=world.ids["B1"],
            owner_id=world.users["beta.admin"].id,
        )
    )
    db_session.flush()


def test_a_contract_cannot_point_at_another_organisations_records(world, db_session) -> None:
    """ID tampering at the database level: alpha's contract with beta's account is refused."""
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    with pytest.raises(IntegrityError, match="fk_contracts_tenant_id_account_id"):
        with db_session.begin_nested():
            db_session.add(_contract(world, account_id=world.ids["B1"]))
            db_session.flush()
    with pytest.raises(IntegrityError, match="fk_contracts_tenant_id_owner_id"):
        with db_session.begin_nested():
            db_session.add(_contract(world, owner_id=world.users["beta.admin"].id))
            db_session.flush()


def test_a_renewal_points_back_at_the_contract_it_replaces(world, db_session) -> None:
    first = _insert(world, db_session, number=1)
    renewal = _contract(world, number=2, renewed_from_id=first.id)
    db_session.add(renewal)
    db_session.flush()
    assert renewal.renewed_from_id == first.id
    with pytest.raises(IntegrityError, match="fk_contracts_tenant_id_renewed_from_id"):
        with db_session.begin_nested():
            db_session.add(_contract(world, number=3, renewed_from_id=uuid.uuid4()))
            db_session.flush()


def test_tenants_only_see_their_own_contracts(world, committed_world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    # Built as the owner (it bypasses RLS), then read back as the restricted app role.
    committed_world.add_all(
        [
            Contract(
                tenant_id=alpha,
                number=1,
                title="Alpha contract",
                account_id=world.ids["A1"],
                owner_id=world.users["alpha.agent1"].id,
            ),
            Contract(
                tenant_id=beta,
                number=1,
                title="Beta contract",
                account_id=world.ids["B1"],
                owner_id=world.users["beta.admin"].id,
            ),
        ]
    )
    committed_world.commit()

    clear_tenant(db_session)
    assert db_session.scalars(select(Contract)).all() == []  # no tenant context: nothing visible
    bind_tenant(db_session, alpha)
    assert [c.title for c in db_session.scalars(select(Contract))] == ["Alpha contract"]
    bind_tenant(db_session, beta)
    assert [c.title for c in db_session.scalars(select(Contract))] == ["Beta contract"]


def test_a_tenant_cannot_write_a_contract_into_another_tenant(world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)
    with pytest.raises(ProgrammingError, match="row-level security"), db_session.begin_nested():
        db_session.add(
            Contract(
                tenant_id=beta,
                number=1,
                title="Planted in beta",
                account_id=world.ids["B1"],
                owner_id=world.users["beta.admin"].id,
            )
        )
        db_session.flush()


def test_the_history_is_insert_only_for_the_application(world, db_session) -> None:
    contract = _insert(world, db_session)
    event = ContractEvent(
        tenant_id=contract.tenant_id,
        contract_id=contract.id,
        event_type="created",
        to_status="draft",
        actor_user_id=world.users["alpha.agent1"].id,
        note="Draft created",
    )
    db_session.add(event)
    db_session.flush()
    assert event.seq is not None  # a database-assigned order for the timeline

    with pytest.raises(DBAPIError, match="permission denied"), db_session.begin_nested():
        db_session.execute(
            text("update contract_events set note = 'edited' where id = :id"), {"id": event.id}
        )
    with pytest.raises(DBAPIError, match="permission denied"), db_session.begin_nested():
        db_session.execute(text("delete from contract_events where id = :id"), {"id": event.id})

    with pytest.raises(IntegrityError, match="event_type_allowed"), db_session.begin_nested():
        db_session.add(
            ContractEvent(
                tenant_id=contract.tenant_id, contract_id=contract.id, event_type="gossip"
            )
        )
        db_session.flush()


def test_each_organisation_has_its_own_number_counter(world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)
    db_session.add(ContractNumberCounter(tenant_id=alpha, last_number=5))
    db_session.flush()
    with pytest.raises(ProgrammingError, match="row-level security"), db_session.begin_nested():
        db_session.add(ContractNumberCounter(tenant_id=beta, last_number=1))
        db_session.flush()
