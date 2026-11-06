"""Fill a DEMO organisation with many fictional customers, so the screens can be tried with volume.

    python -m scripts.seed_demo_volume --tenant-slug demo-fictional            add (default 1000)
    python -m scripts.seed_demo_volume --tenant-slug demo-fictional --accounts 200 --leads 50
    python -m scripts.seed_demo_volume --tenant-slug demo-fictional --remove   take them out again

What it adds (all invented): accounts (Indian real-estate style company names, cities, segments),
one primary contact per account, leads with property wishes and budgets, and open/closed deals.
E-mail addresses end in ``@example.com`` (a domain reserved for examples, so nothing is ever
delivered) and phone numbers use the +91 90000 range. Consent is "unknown", so no campaign e-mail
can be sent to them.

Rules:
- Only an organisation whose short name contains ``demo`` is accepted: this can never write
  into a real organisation by a typo.
- The organisation must already exist and have at least one active staff user; records are
  spread over its staff as owners. Nobody is created in Keycloak.
- Every id is derived from the organisation and a running number (uuid5), so a second run adds
  nothing twice, and ``--remove`` deletes exactly what this script made - nothing typed by people.
- Connects as the schema owner (CRM_MIGRATION_DATABASE_URL, like Alembic and seed_dev_data): the
  rows are written for one organisation, outside the request path. Setup, not application use.
"""

import argparse
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import MigrationSettings
from app.model_registry import metadata

NAMESPACE = uuid.UUID("3f7f4c1e-9d55-4b8a-9a35-2c7d0a5e9b11")
SEED = 20261106

FIRST = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Vihaan",
    "Arjun",
    "Sai",
    "Reyansh",
    "Krishna",
    "Ishaan",
    "Rohan",
    "Ananya",
    "Diya",
    "Saanvi",
    "Aadhya",
    "Pari",
    "Anika",
    "Navya",
    "Meera",
    "Kavya",
    "Priya",
    "Lakshmi",
    "Ravi",
    "Suresh",
    "Ramesh",
    "Lalitha",
    "Harini",
    "Karthik",
    "Venkat",
    "Srinivas",
    "Padma",
]
LAST = [
    "Sharma",
    "Reddy",
    "Naidu",
    "Iyer",
    "Rao",
    "Patel",
    "Gupta",
    "Kumar",
    "Menon",
    "Nair",
    "Chowdary",
    "Verma",
    "Joshi",
    "Pillai",
    "Shetty",
    "Kulkarni",
    "Desai",
    "Bose",
    "Das",
    "Varma",
]
WORDS = [
    "Sunrise",
    "Lotus",
    "Silver Oak",
    "Green Valley",
    "Royal",
    "Skyline",
    "Lakeview",
    "Palm Grove",
    "Heritage",
    "Pearl",
    "Orchid",
    "Emerald",
    "Golden Gate",
    "Riverside",
    "Maple",
    "Sapphire",
    "Banyan",
    "Horizon",
    "Crescent",
    "Meadows",
]
KINDS = [
    "Realty",
    "Builders",
    "Developers",
    "Estates",
    "Infra",
    "Homes",
    "Constructions",
    "Properties",
    "Ventures",
    "Housing",
]
CITIES = [
    ("Hyderabad", "Telangana"),
    ("Bengaluru", "Karnataka"),
    ("Chennai", "Tamil Nadu"),
    ("Pune", "Maharashtra"),
    ("Mumbai", "Maharashtra"),
    ("Vijayawada", "Andhra Pradesh"),
    ("Visakhapatnam", "Andhra Pradesh"),
    ("Tirupati", "Andhra Pradesh"),
    ("Anantapur", "Andhra Pradesh"),
    ("Kochi", "Kerala"),
    ("Ahmedabad", "Gujarat"),
    ("Noida", "Uttar Pradesh"),
]
INDUSTRIES = [
    "Real estate",
    "Construction",
    "Property management",
    "Interior design",
    "Facility services",
]
SEGMENTS = ["enterprise", "mid_market", "small_business"]
LIFECYCLE = ["prospect", "onboarding", "active_customer"]
CHANNELS = ["email", "phone", "mobile"]
TITLES = ["Director", "Purchase Manager", "Owner", "Sales Head", "Project Manager", "Partner"]
LEAD_STATUS = ["new"] * 4 + ["contacted"] * 3 + ["qualified"] * 2 + ["unqualified"]
PROPERTY = ["apartment", "villa", "plot", "commercial"]
SOURCES = ["web", "referral", "phone", "event", "partner"]
PROJECTS = ["Tower A", "Phase 2", "Villas", "Plots"]
OPEN_STAGES = ["prospecting", "qualification", "proposal", "negotiation"]


@dataclass(frozen=True)
class Report:
    accounts: int
    contacts: int
    leads: int
    deals: int


def _id(tenant_id: uuid.UUID, kind: str, n: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{tenant_id}:{kind}:{n}")


def _phone(rng: random.Random) -> str:
    return f"+91 90000 {rng.randint(10000, 99999)}"


def find_tenant(connection: Connection, slug: str) -> uuid.UUID:
    if "demo" not in slug:
        raise SystemExit(
            f"Refused: '{slug}' is not a demo organisation (its short name must contain 'demo')."
        )
    tenants = metadata.tables["tenants"]
    tenant_id = connection.scalar(select(tenants.c.id).where(tenants.c.slug == slug))
    if tenant_id is None:
        raise SystemExit(f"No organisation with the short name '{slug}'. Create it first.")
    return uuid.UUID(str(tenant_id))


def staff_owners(connection: Connection, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    users = metadata.tables["users"]
    rows = connection.scalars(
        select(users.c.id)
        .where(users.c.tenant_id == tenant_id)
        .where(users.c.user_type == "staff")
        .where(users.c.is_active.is_(True))
        .order_by(users.c.created_at)
    ).all()
    if not rows:
        raise SystemExit("The organisation has no active staff user to own the records.")
    return [uuid.UUID(str(r)) for r in rows]


def build(
    tenant_id: uuid.UUID, owners: list[uuid.UUID], *, accounts: int, leads: int, deals: int
) -> dict[str, list[dict[str, Any]]]:
    # Repeatable fake data, not security: the same organisation always gets the same rows.
    rng = random.Random(f"{SEED}:{tenant_id}")  # noqa: S311
    now = datetime.now(UTC)
    rows: dict[str, list[dict[str, Any]]] = {
        "accounts": [],
        "contacts": [],
        "leads": [],
        "opportunities": [],
    }
    for n in range(accounts):
        city, region = rng.choice(CITIES)
        name = f"{rng.choice(WORDS)} {rng.choice(KINDS)} {n + 1:04d}"
        account_id = _id(tenant_id, "account", n)
        owner = owners[n % len(owners)]
        rows["accounts"].append(
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "name": name,
                "account_number": f"DEMO-{n + 1:05d}",
                "industry": rng.choice(INDUSTRIES),
                "phone": _phone(rng),
                "status": "active" if rng.random() < 0.92 else "inactive",
                "owner_id": owner,
                "segment": rng.choice(SEGMENTS),
                "preferred_channel": rng.choice(CHANNELS),
                "country": "IN",
                "region": region,
                "city": city,
                "lifecycle_stage": rng.choice(LIFECYCLE),
                "account_type": "company",
                "preferred_language": "en",
            }
        )
        first, last = rng.choice(FIRST), rng.choice(LAST)
        rows["contacts"].append(
            {
                "id": _id(tenant_id, "contact", n),
                "tenant_id": tenant_id,
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}.{n + 1}@example.com",
                "phone": _phone(rng),
                "mobile": _phone(rng),
                "job_title": rng.choice(TITLES),
                "account_id": account_id,
                "owner_id": owner,
                "is_primary": True,
                "preferred_channel": rng.choice(CHANNELS),
                "email_consent": "unknown",
                "do_not_call": False,
                "preferred_language": "en",
            }
        )
    for n in range(leads):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        low = rng.choice([30, 45, 60, 80, 100, 150, 200, 300]) * 100_000  # 30 L to 3 Cr
        city, _ = rng.choice(CITIES)
        rows["leads"].append(
            {
                "id": _id(tenant_id, "lead", n),
                "tenant_id": tenant_id,
                "first_name": first,
                "last_name": last,
                "company_name": None if rng.random() < 0.6 else f"{rng.choice(WORDS)} Group",
                "email": f"lead.{first.lower()}.{n + 1}@example.com",
                "phone": _phone(rng),
                "status": rng.choice(LEAD_STATUS),
                "source": rng.choice(SOURCES),
                "owner_id": owners[n % len(owners)] if rng.random() < 0.8 else None,
                "property_type": rng.choice(PROPERTY),
                "budget_min_inr": low,
                "budget_max_inr": low + rng.choice([10, 20, 50]) * 100_000,
                "location": city,
            }
        )
    for n in range(min(deals, accounts)):
        index = (n * max(1, accounts // max(deals, 1))) % accounts
        account = rows["accounts"][index]
        stage = rng.choice(OPEN_STAGES * 3 + ["closed_won", "closed_lost"])
        closed = stage in ("closed_won", "closed_lost")
        rows["opportunities"].append(
            {
                "id": _id(tenant_id, "deal", n),
                "tenant_id": tenant_id,
                "name": f"{account['name']} - {rng.choice(PROJECTS)}",
                "account_id": account["id"],
                "primary_contact_id": _id(tenant_id, "contact", index),
                "owner_id": account["owner_id"],
                "stage": stage,
                "amount": Decimal(rng.choice([25, 40, 60, 90, 120, 250])) * Decimal(100_000),
                "currency": "INR",
                "expected_close_date": date.today() + timedelta(days=rng.randint(-60, 180)),
                "closed_at": now - timedelta(days=rng.randint(1, 60)) if closed else None,
                "lost_reason": "Budget not approved (demo)" if stage == "closed_lost" else None,
                "next_step": None if closed else "Site visit (demo)",
            }
        )
    return rows


def seed(connection: Connection, slug: str, *, accounts: int, leads: int, deals: int) -> Report:
    tenant_id = find_tenant(connection, slug)
    rows = build(
        tenant_id, staff_owners(connection, tenant_id), accounts=accounts, leads=leads, deals=deals
    )
    added: dict[str, int] = {}
    for table in ("accounts", "contacts", "leads", "opportunities"):
        before = _count(connection, table, tenant_id)
        for start in range(0, len(rows[table]), 500):
            statement = pg_insert(metadata.tables[table]).on_conflict_do_nothing(
                index_elements=["id"]
            )
            if rows[table][start : start + 500]:
                connection.execute(statement, rows[table][start : start + 500])
        added[table] = _count(connection, table, tenant_id) - before
    return Report(added["accounts"], added["contacts"], added["leads"], added["opportunities"])


def remove(connection: Connection, slug: str, *, up_to: int = 100_000) -> Report:
    """Deletes only this script's rows (their ids are derived), children first."""
    tenant_id = find_tenant(connection, slug)
    removed: dict[str, int] = {}
    for table, kind in (
        ("opportunities", "deal"),
        ("leads", "lead"),
        ("contacts", "contact"),
        ("accounts", "account"),
    ):
        tab = metadata.tables[table]
        ids = [_id(tenant_id, kind, n) for n in range(up_to)]
        total = 0
        for start in range(0, len(ids), 5000):
            result = connection.execute(
                delete(tab)
                .where(tab.c.tenant_id == tenant_id)
                .where(tab.c.id.in_(ids[start : start + 5000]))
            )
            total += result.rowcount or 0
        removed[table] = total
    return Report(
        removed["accounts"], removed["contacts"], removed["leads"], removed["opportunities"]
    )


def _count(connection: Connection, table: str, tenant_id: uuid.UUID) -> int:
    tab = metadata.tables[table]
    return int(
        connection.scalar(select(func.count()).select_from(tab).where(tab.c.tenant_id == tenant_id))
        or 0
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--accounts", type=int, default=1000)
    parser.add_argument("--leads", type=int, default=300)
    parser.add_argument("--deals", type=int, default=150)
    parser.add_argument("--remove", action="store_true", help="delete what this script added")
    args = parser.parse_args()
    for name in ("accounts", "leads", "deals"):
        if not 0 <= getattr(args, name) <= 20_000:
            parser.error(f"--{name} must be between 0 and 20000")
    engine = create_engine(MigrationSettings().migration_database_url.get_secret_value())
    with engine.begin() as connection:
        if args.remove:
            r = remove(connection, args.tenant_slug)
            print(
                f"removed: {r.accounts} accounts, {r.contacts} contacts, {r.leads} leads, "
                f"{r.deals} deals"
            )
        else:
            r = seed(
                connection,
                args.tenant_slug,
                accounts=args.accounts,
                leads=args.leads,
                deals=args.deals,
            )
            print(
                f"added: {r.accounts} accounts, {r.contacts} contacts, {r.leads} leads, "
                f"{r.deals} deals"
            )


if __name__ == "__main__":
    main()
