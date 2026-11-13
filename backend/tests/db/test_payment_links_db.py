"""Payment links and webhook events - what the DATABASE guarantees (ADR 0031, UP1).

Real PostgreSQL, rolled back. Rows are written as the application role under the tenant's context.
Invoices come from the real invoices API so the foreign keys are real.
"""

# ruff: noqa: F811 - the fixtures are imported and used by name

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import TENANT_SETTING, bind_tenant
from app.modules.payment_links.models import PaymentEvent, PaymentLink
from tests.db.test_invoices_api import (  # noqa: F401 - fixtures used by name
    World,
    api,
    auth,
    issued_invoice,
    world,
)

SOON = datetime.now(UTC) + timedelta(days=7)
_counter = iter(range(1, 10_000))


def link_values(world: World, invoice_id: str, **over: Any) -> dict[str, Any]:
    n = next(_counter)
    values: dict[str, Any] = {
        "tenant_id": world.users["alpha.admin"].tenant_id,
        "invoice_id": uuid.UUID(invoice_id),
        "created_by_user_id": world.users["alpha.admin"].id,
        "provider_link_id": f"plink_t{n:05d}",
        "reference_id": f"ref{n:05d}",
        "short_url": f"https://pay.fake.invalid/{n}",
        "amount_paise": 21416,
        "expires_at": SOON,
    }
    values.update(over)
    return values


@pytest.fixture
def invoice(api, auth, world) -> str:
    return str(issued_invoice(api, auth, world.accounts["A1"])["id"])


def alpha(world: World, session: Session) -> uuid.UUID:
    tenant = world.users["alpha.admin"].tenant_id
    bind_tenant(session, tenant)
    return tenant


def add_link(world: World, session: Session, invoice_id: str, **over: Any) -> PaymentLink:
    alpha(world, session)
    link = PaymentLink(**link_values(world, invoice_id, **over))
    session.add(link)
    session.flush()
    return link


def add_event(session: Session, link: PaymentLink, **over: Any) -> PaymentEvent:
    values: dict[str, Any] = {
        "tenant_id": link.tenant_id,
        "payment_link_id": link.id,
        "provider_event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "event_type": "payment_link.paid",
        "body_sha256": "a" * 64,
        "facts": {"payment_id": "pay_1", "amount_paise": 21416, "currency": "INR"},
    }
    values.update(over)
    event = PaymentEvent(**values)
    session.add(event)
    session.flush()
    return event


def refused(session: Session, sql: str, **params: Any) -> None:
    with pytest.raises((DBAPIError, IntegrityError)):
        with session.begin_nested():
            session.execute(text(sql), params)


# --- links -----------------------------------------------------------------------------------


def test_a_link_is_stored_open(db_session, world, invoice) -> None:
    link = add_link(world, db_session, invoice)
    assert (link.status, link.currency, link.provider_payment_id) == ("created", "INR", None)


def test_an_invoice_has_at_most_one_open_link(db_session, world, invoice) -> None:
    add_link(world, db_session, invoice)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            add_link(world, db_session, invoice)


def test_a_new_link_is_allowed_once_the_old_one_is_cancelled(db_session, world, invoice) -> None:
    first = add_link(world, db_session, invoice)
    db_session.execute(
        text("update payment_links set status = 'cancelled' where id = :i"), {"i": first.id}
    )
    assert add_link(world, db_session, invoice).status == "created"


def test_cancelled_and_expired_links_can_pile_up(db_session, world, invoice) -> None:
    for status in ("cancelled", "expired", "cancelled"):
        add_link(world, db_session, invoice, status=status)
    count = db_session.scalar(text("select count(*) from payment_links"))
    assert count == 3


def test_a_provider_link_id_can_not_repeat(db_session, world, invoice) -> None:
    add_link(world, db_session, invoice, provider_link_id="plink_same", status="cancelled")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            add_link(world, db_session, invoice, provider_link_id="plink_same", status="cancelled")


def test_a_reference_can_not_repeat_within_an_organisation(db_session, world, invoice) -> None:
    add_link(world, db_session, invoice, reference_id="r-1", status="cancelled")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            add_link(world, db_session, invoice, reference_id="r-1", status="cancelled")


@pytest.mark.parametrize(
    "over",
    [
        {"status": "weird"},
        {"currency": "USD"},
        {"amount_paise": 99},
        {"amount_paise": 0},
        {"amount_paise": 10_00_00_000 * 100 + 1},
        {"status": "paid"},  # a paid link needs the provider's payment id and a time
        {"status": "paid", "provider_payment_id": "pay_1"},  # ... and the time
        {"status": "created", "provider_payment_id": "pay_1"},  # only a paid link has one
        {"reference_id": "x" * 41},
    ],
)
def test_the_database_refuses_impossible_links(db_session, world, invoice, over) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            add_link(world, db_session, invoice, **over)


def test_a_paid_link_with_payment_and_time_is_fine(db_session, world, invoice) -> None:
    link = add_link(
        world,
        db_session,
        invoice,
        status="paid",
        provider_payment_id="pay_1",
        paid_at=datetime.now(UTC),
    )
    assert link.status == "paid"


def test_the_invoice_must_exist_in_the_same_organisation(db_session, world, invoice) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            add_link(world, db_session, str(uuid.uuid4()))


def test_another_organisations_invoice_can_not_be_linked(db_session, world, invoice) -> None:
    """Even with the right invoice id, the beta organisation cannot attach it to its own link."""
    beta = world.users["beta.admin"]
    bind_tenant(db_session, beta.tenant_id)
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            db_session.add(
                PaymentLink(
                    **link_values(
                        world,
                        invoice,
                        tenant_id=beta.tenant_id,
                        created_by_user_id=beta.id,
                    )
                )
            )
            db_session.flush()


def test_the_application_can_not_delete_a_link(db_session, world, invoice) -> None:
    link = add_link(world, db_session, invoice)
    refused(db_session, "delete from payment_links where id = :i", i=link.id)


def test_a_link_of_another_organisation_is_invisible(db_session, world, invoice) -> None:
    add_link(world, db_session, invoice)
    bind_tenant(db_session, world.users["beta.admin"].tenant_id)
    assert db_session.scalars(select(PaymentLink)).all() == []


def test_without_an_organisation_no_link_can_be_read(db_session, world, invoice) -> None:
    add_link(world, db_session, invoice)
    db_session.info.pop("tenant_id", None)
    db_session.execute(text("select set_config(:n, '', true)"), {"n": TENANT_SETTING})
    assert db_session.scalars(select(PaymentLink)).all() == []


# --- the webhook lookup ----------------------------------------------------------------------


def test_the_lookup_finds_the_organisation_without_a_context(db_session, world, invoice) -> None:
    link = add_link(world, db_session, invoice, provider_link_id="plink_lookup")
    db_session.info.pop("tenant_id", None)
    db_session.execute(text("select set_config(:n, '', true)"), {"n": TENANT_SETTING})
    found = db_session.scalar(text("select payment_link_tenant('plink_lookup')"))
    assert found == link.tenant_id
    assert db_session.scalar(text("select payment_link_tenant('plink_unknown')")) is None


def test_the_lookup_returns_nothing_else(db_session) -> None:
    columns = db_session.execute(
        text(
            "select pg_get_function_result(p.oid), p.prosecdef from pg_proc p "
            "where p.proname = 'payment_link_tenant'"
        )
    ).one()
    assert columns[0] == "uuid" and columns[1] is True


# --- events ----------------------------------------------------------------------------------


def test_an_event_is_stored_unprocessed(db_session, world, invoice) -> None:
    event = add_event(db_session, add_link(world, db_session, invoice))
    assert (event.outcome, event.processed_at) == (None, None)


def test_the_same_event_id_can_not_be_stored_twice(db_session, world, invoice) -> None:
    link = add_link(world, db_session, invoice)
    add_event(db_session, link, provider_event_id="evt_dup")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            add_event(db_session, link, provider_event_id="evt_dup")


def test_the_worker_can_record_the_outcome_once(db_session, world, invoice) -> None:
    event = add_event(db_session, add_link(world, db_session, invoice))
    db_session.execute(
        text("update payment_events set outcome = 'applied', processed_at = now() where id = :i"),
        {"i": event.id},
    )
    refused(
        db_session,
        "update payment_events set outcome = 'ignored', processed_at = now() where id = :i",
        i=event.id,
    )


@pytest.mark.parametrize(
    "column_change",
    [
        "facts = '{}'::jsonb",
        "body_sha256 = repeat('b', 64)",
        "event_type = 'payment_link.cancelled'",
        "provider_event_id = 'evt_other'",
        "created_at = now() - interval '2 years'",
    ],
)
def test_nothing_but_the_outcome_can_be_changed(db_session, world, invoice, column_change) -> None:
    event = add_event(db_session, add_link(world, db_session, invoice))
    sql = f"update payment_events set {column_change} where id = :i"  # noqa: S608
    refused(db_session, sql, i=event.id)


def test_the_trigger_also_binds_an_update_of_both_kinds_of_column(
    db_session, world, invoice
) -> None:
    """Outcome together with another column is refused as a whole."""
    event = add_event(db_session, add_link(world, db_session, invoice))
    refused(
        db_session,
        "update payment_events set outcome = 'applied', processed_at = now(), "
        "facts = '{}'::jsonb where id = :i",
        i=event.id,
    )


def test_an_outcome_needs_a_time_and_a_time_needs_an_outcome(db_session, world, invoice) -> None:
    event = add_event(db_session, add_link(world, db_session, invoice))
    refused(db_session, "update payment_events set outcome = 'applied' where id = :i", i=event.id)
    refused(db_session, "update payment_events set processed_at = now() where id = :i", i=event.id)


def test_an_unknown_outcome_is_refused(db_session, world, invoice) -> None:
    event = add_event(db_session, add_link(world, db_session, invoice))
    refused(
        db_session,
        "update payment_events set outcome = 'paid_in_full', processed_at = now() where id = :i",
        i=event.id,
    )


def test_facts_must_be_an_object(db_session, world, invoice) -> None:
    link = add_link(world, db_session, invoice)
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            add_event(db_session, link, facts=["not", "an", "object"])


def test_a_fresh_event_can_not_be_deleted(db_session, world, invoice) -> None:
    event = add_event(db_session, add_link(world, db_session, invoice))
    refused(db_session, "delete from payment_events where id = :i", i=event.id)


def test_the_application_role_has_no_table_wide_update(db_session) -> None:
    """The second lock: only the two bookkeeping columns carry an UPDATE grant."""
    rows = db_session.execute(
        text(
            "select column_name from information_schema.column_privileges "
            "where table_name = 'payment_events' and privilege_type = 'UPDATE' "
            "and grantee = 'crm_app' order by column_name"
        )
    ).scalars()
    assert list(rows) == ["outcome", "processed_at"]


def test_events_of_another_organisation_are_invisible(db_session, world, invoice) -> None:
    add_event(db_session, add_link(world, db_session, invoice))
    bind_tenant(db_session, world.users["beta.admin"].tenant_id)
    assert db_session.scalars(select(PaymentEvent)).all() == []


def test_an_event_can_not_point_at_another_organisations_link(db_session, world, invoice) -> None:
    link = add_link(world, db_session, invoice)
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, beta)
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            db_session.add(
                PaymentEvent(
                    tenant_id=beta,
                    payment_link_id=link.id,
                    provider_event_id="evt_cross",
                    event_type="payment_link.paid",
                    body_sha256="a" * 64,
                    facts={},
                )
            )
            db_session.flush()
