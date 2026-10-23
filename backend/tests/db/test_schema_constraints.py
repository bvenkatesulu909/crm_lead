"""The database itself must enforce tenant ownership and data rules.

All data here is invented test data (".example.test" addresses), never real customers.
Each test runs inside a transaction that is rolled back afterwards.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.db import bind_tenant
from app.modules.accounts.models import Account
from app.modules.contacts.models import Contact
from app.modules.identity.models import Tenant, User
from app.modules.leads.models import Lead
from tests.db.conftest import setup_lead_context

TEST_ISSUER = "http://localhost:8080/realms/crm"


def make_tenant(session: Session, slug: str) -> Tenant:
    tenant = Tenant(slug=slug, name=f"Test tenant {slug}")
    session.add(tenant)
    session.flush()
    return tenant


def make_user(session: Session, tenant: Tenant, email: str = "staff@example.test") -> User:
    # users is RLS-protected: insert with the tenant context a real request would have.
    bind_tenant(session, tenant.id)
    user = User(
        tenant_id=tenant.id,
        idp_issuer=TEST_ISSUER,
        idp_subject=str(uuid.uuid4()),
        email=email,
        display_name="Test Staff",
        user_type="staff",
    )
    session.add(user)
    session.flush()
    return user


def make_account(session: Session, tenant: Tenant, **fields: object) -> Account:
    bind_tenant(session, tenant.id)  # accounts is RLS-protected, like users
    account = Account(tenant_id=tenant.id, name="Test Account Ltd", **fields)
    session.add(account)
    session.flush()
    return account


def violated_constraint(error: pytest.ExceptionInfo[IntegrityError]) -> str | None:
    name: str | None = error.value.orig.diag.constraint_name  # type: ignore[union-attr]
    return name


def test_database_generates_ids_timestamps_and_defaults(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    account = make_account(db_session, tenant)

    assert isinstance(account.id, uuid.UUID)
    assert account.created_at is not None
    assert account.status == "active"
    assert account.version == 1
    assert account.deleted_at is None


def test_tenant_slug_format_is_enforced(db_session: Session) -> None:
    db_session.add(Tenant(slug="Not A Slug", name="Bad"))

    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert violated_constraint(error) == "ck_tenants_slug_format"


def test_account_number_is_unique_per_tenant_only(db_session: Session) -> None:
    tenant_a = make_tenant(db_session, "alpha")
    tenant_b = make_tenant(db_session, "beta")
    make_account(db_session, tenant_a, account_number="ACC-001")
    make_account(db_session, tenant_b, account_number="ACC-001")  # other tenant: allowed

    with pytest.raises(IntegrityError) as error:
        make_account(db_session, tenant_a, account_number="ACC-001")
    assert violated_constraint(error) == "uq_accounts_tenant_id_account_number"


def test_user_email_is_unique_per_tenant_ignoring_case(db_session: Session) -> None:
    tenant_a = make_tenant(db_session, "alpha")
    tenant_b = make_tenant(db_session, "beta")
    make_user(db_session, tenant_a, "pat@example.test")
    make_user(db_session, tenant_b, "pat@example.test")  # other tenant: allowed

    with pytest.raises(IntegrityError) as error:
        make_user(db_session, tenant_a, "PAT@Example.TEST")
    assert violated_constraint(error) == "uq_users_tenant_id_lower_email"


def test_contact_cannot_link_to_account_of_another_tenant(db_session: Session) -> None:
    tenant_a = make_tenant(db_session, "alpha")
    tenant_b = make_tenant(db_session, "beta")
    account_of_a = make_account(db_session, tenant_a)

    bind_tenant(db_session, tenant_b.id)  # the contact's own tenant: only the FK may object
    db_session.add(Contact(tenant_id=tenant_b.id, last_name="Tester", account_id=account_of_a.id))
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert violated_constraint(error) == "fk_contacts_tenant_id_account_id_accounts"


def test_lead_owner_must_be_user_of_same_tenant(db_session: Session) -> None:
    tenant_a = make_tenant(db_session, "alpha")
    tenant_b = make_tenant(db_session, "beta")
    user_of_a = make_user(db_session, tenant_a)
    setup_lead_context(db_session, tenant_b.id)

    db_session.add(Lead(tenant_id=tenant_b.id, last_name="Prospect", owner_id=user_of_a.id))
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert violated_constraint(error) == "fk_leads_tenant_id_owner_id_users"


def test_parent_account_must_belong_to_same_tenant(db_session: Session) -> None:
    tenant_a = make_tenant(db_session, "alpha")
    tenant_b = make_tenant(db_session, "beta")
    parent_in_a = make_account(db_session, tenant_a)

    with pytest.raises(IntegrityError) as error:
        make_account(db_session, tenant_b, parent_account_id=parent_in_a.id)
    assert violated_constraint(error) == "fk_accounts_tenant_id_parent_account_id_accounts"


def _converted_records(session: Session, tenant: Tenant) -> dict[str, object]:
    account = make_account(session, tenant)
    contact = Contact(tenant_id=tenant.id, last_name="Converted", account_id=account.id)
    session.add(contact)
    session.flush()
    return {"converted_account_id": account.id, "converted_contact_id": contact.id}


def test_converted_lead_requires_conversion_time(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    records = _converted_records(db_session, tenant)
    setup_lead_context(db_session, tenant.id)
    db_session.add(
        Lead(
            tenant_id=tenant.id,
            last_name="Ok",
            status="converted",
            converted_at=datetime.now(UTC),
            **records,
        )
    )
    db_session.flush()  # consistent: accepted

    db_session.add(Lead(tenant_id=tenant.id, last_name="Broken", status="converted", **records))
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert violated_constraint(error) == "ck_leads_converted_consistent"


def test_converted_lead_must_point_to_account_and_contact(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    setup_lead_context(db_session, tenant.id)
    db_session.add(
        Lead(tenant_id=tenant.id, last_name="X", status="converted", converted_at=datetime.now(UTC))
    )

    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert violated_constraint(error) == "ck_leads_converted_has_records"


def test_tenant_that_owns_data_cannot_be_deleted(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    make_user(db_session, tenant)

    with pytest.raises(IntegrityError) as error:
        db_session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant.id})
    assert violated_constraint(error) == "fk_users_tenant_id_tenants"


def test_concurrent_update_is_detected_by_version_column(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    account = make_account(db_session, tenant)
    # Simulate another request updating the same row in the meantime.
    db_session.execute(
        text("UPDATE accounts SET version = version + 1 WHERE id = :id"), {"id": account.id}
    )

    account.name = "Lost update"
    with pytest.raises(StaleDataError):
        db_session.flush()
