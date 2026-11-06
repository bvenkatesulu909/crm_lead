"""The demo-volume seed (scripts/seed_demo_volume.py) against the real test database.

Runs as the owner role inside one transaction that is rolled back, so nothing stays behind.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, func, select

from app.model_registry import metadata
from scripts import seed_demo_volume as demo

TABLES = ("accounts", "contacts", "leads", "opportunities")


@pytest.fixture
def owner_tx(owner_engine: Engine) -> Iterator[Connection]:
    with owner_engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def make_tenant(connection: Connection, slug: str, *, staff: bool = True) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    connection.execute(
        metadata.tables["tenants"].insert(), {"id": tenant_id, "slug": slug, "name": slug}
    )
    if staff:
        connection.execute(
            metadata.tables["users"].insert(),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "idp_issuer": "https://login.example.test/realms/crm",
                "idp_subject": str(uuid.uuid4()),
                "email": f"admin@{slug}.example.test",
                "display_name": "Admin",
                "user_type": "staff",
                "roles": ["tenant_admin"],
            },
        )
    return tenant_id


def counts(connection: Connection, tenant_id: uuid.UUID) -> dict[str, int]:
    out = {}
    for name in TABLES:
        table = metadata.tables[name]
        out[name] = int(
            connection.scalar(
                select(func.count()).select_from(table).where(table.c.tenant_id == tenant_id)
            )
            or 0
        )
    return out


def test_it_fills_a_demo_organisation_once_and_removes_exactly_its_rows(
    owner_tx: Connection,
) -> None:
    demo_id = make_tenant(owner_tx, "demo-volume-test")
    other_id = make_tenant(owner_tx, "real-company-test")

    report = demo.seed(owner_tx, "demo-volume-test", accounts=40, leads=15, deals=10)
    assert report == demo.Report(accounts=40, contacts=40, leads=15, deals=10)
    assert counts(owner_tx, demo_id) == {
        "accounts": 40,
        "contacts": 40,
        "leads": 15,
        "opportunities": 10,
    }
    assert counts(owner_tx, other_id) == dict.fromkeys(TABLES, 0)

    again = demo.seed(owner_tx, "demo-volume-test", accounts=40, leads=15, deals=10)
    assert again == demo.Report(0, 0, 0, 0)

    contacts = metadata.tables["contacts"]
    emails = owner_tx.scalars(select(contacts.c.email).where(contacts.c.tenant_id == demo_id))
    assert all(e.endswith("@example.com") for e in emails)
    consents = set(
        owner_tx.scalars(select(contacts.c.email_consent).where(contacts.c.tenant_id == demo_id))
    )
    assert consents == {"unknown"}

    removed = demo.remove(owner_tx, "demo-volume-test", up_to=1000)
    assert removed == demo.Report(40, 40, 15, 10)
    assert counts(owner_tx, demo_id) == dict.fromkeys(TABLES, 0)


def test_rows_typed_by_people_survive_remove(owner_tx: Connection) -> None:
    demo_id = make_tenant(owner_tx, "demo-keep-test")
    demo.seed(owner_tx, "demo-keep-test", accounts=5, leads=0, deals=0)
    accounts = metadata.tables["accounts"]
    owner_tx.execute(
        accounts.insert(), {"id": uuid.uuid4(), "tenant_id": demo_id, "name": "Typed by a person"}
    )
    demo.remove(owner_tx, "demo-keep-test", up_to=100)
    left = owner_tx.scalars(select(accounts.c.name).where(accounts.c.tenant_id == demo_id))
    assert list(left) == ["Typed by a person"]


@pytest.mark.parametrize("slug", ["real-company", "acme-ltd", "crm-lead"])
def test_a_real_organisation_is_refused(owner_tx: Connection, slug: str) -> None:
    make_tenant(owner_tx, slug)
    with pytest.raises(SystemExit, match="not a demo organisation"):
        demo.seed(owner_tx, slug, accounts=1, leads=0, deals=0)
    with pytest.raises(SystemExit, match="not a demo organisation"):
        demo.remove(owner_tx, slug)


def test_a_missing_organisation_or_one_without_staff_is_refused(owner_tx: Connection) -> None:
    with pytest.raises(SystemExit, match="No organisation"):
        demo.seed(owner_tx, "demo-nowhere", accounts=1, leads=0, deals=0)
    make_tenant(owner_tx, "demo-empty-test", staff=False)
    with pytest.raises(SystemExit, match="no active staff user"):
        demo.seed(owner_tx, "demo-empty-test", accounts=1, leads=0, deals=0)
