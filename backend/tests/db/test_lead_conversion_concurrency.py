"""Two requests convert the same lead at the same moment: exactly one conversion may happen.

Unlike the other database tests, this one needs REAL separate transactions (two connections),
so it commits data. It uses its own uniquely named tenant and removes everything afterwards
with the schema-owner role (the app role cannot delete audit rows - that is the point).
"""

import threading
import time
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.modules.accounts.models import Account
from app.modules.contacts.models import Contact
from app.modules.identity.models import Tenant, User
from app.modules.leads import service
from app.modules.leads.models import Lead
from app.modules.leads.schemas import ConversionResult, LeadConvert
from tests.auth_helpers import TEST_ISSUER

CLEANUP_ORDER = [
    "audit_log",
    "lead_activities",
    "lead_assignments",
    "leads",
    "opportunities",
    "contacts",
    "accounts",
    "users",
]


@pytest.fixture
def committed_lead(
    app_engine: Engine, migrated_database: str
) -> Iterator[tuple[Principal, uuid.UUID]]:
    tenant_id = uuid.uuid4()
    with Session(app_engine) as session:
        session.add(Tenant(id=tenant_id, slug=f"race-{tenant_id.hex[:12]}", name="Race test"))
        session.flush()
        manager = User(
            tenant_id=tenant_id,
            idp_issuer=TEST_ISSUER,
            idp_subject=f"race-{tenant_id}",
            email="manager@race.example.test",
            display_name="Race Manager",
            user_type="staff",
            roles=["sales_manager"],
        )
        session.add(manager)
        session.flush()
        lead = Lead(tenant_id=tenant_id, last_name="Racer", status="qualified", owner_id=manager.id)
        session.add(lead)
        session.commit()
        principal = Principal(
            subject=manager.idp_subject,
            issuer=TEST_ISSUER,
            user_type="staff",
            roles=frozenset({Role.SALES_MANAGER}),
            permissions=permissions_for(frozenset({Role.SALES_MANAGER})),
            user_id=manager.id,
            tenant_id=tenant_id,
        )
        lead_id = lead.id
    try:
        yield principal, lead_id
    finally:
        owner = create_engine(migrated_database, poolclass=NullPool)
        with owner.begin() as connection:
            for table in CLEANUP_ORDER:
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608 - fixed names
                    {"t": tenant_id},
                )
            connection.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        owner.dispose()


def test_simultaneous_conversions_create_records_only_once(app_engine, committed_lead) -> None:
    principal, lead_id = committed_lead
    start = threading.Barrier(2)
    results: list[ConversionResult] = []
    errors: list[BaseException] = []

    def convert() -> None:
        try:
            with Session(app_engine) as session:
                start.wait()  # both threads begin at the same moment
                result = service.convert_lead(session, principal, lead_id, LeadConvert())
                time.sleep(0.5)  # hold the transaction open to widen the race window
                session.commit()
                results.append(result)
        except BaseException as exc:  # noqa: BLE001 - re-raised below on the main thread
            errors.append(exc)

    threads = [threading.Thread(target=convert) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert sorted(r.already_converted for r in results) == [False, True]
    assert results[0].account_id == results[1].account_id
    assert results[0].contact_id == results[1].contact_id
    with Session(app_engine) as session:
        tenant = principal.tenant_id
        accounts = session.scalar(
            select(func.count()).select_from(Account).where(Account.tenant_id == tenant)
        )
        contacts = session.scalar(
            select(func.count()).select_from(Contact).where(Contact.tenant_id == tenant)
        )
    assert (accounts, contacts) == (1, 1)
