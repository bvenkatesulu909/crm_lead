"""Create the local development data that matches the Keycloak test identities.

Run from the backend folder (venv active, PostgreSQL running, migrations applied):

    python -m scripts.seed_dev_data

Connects with CRM_MIGRATION_DATABASE_URL (the owner role, like Alembic): the app role is
subject to row-level security (ADR 0009) and could not create users for a tenant before a
tenant context exists. Seeding is setup, not application behaviour, so it uses the owner.

Safe to run repeatedly: existing rows are left unchanged. All names and e-mail addresses are
invented (".example.test"). The user IDs equal the fixed Keycloak user IDs in
infrastructure/keycloak/realm-crm.json, so a login maps to the right CRM user.
"""

import uuid
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import MigrationSettings, Settings
from app.model_registry import metadata

TENANT_ALPHA = uuid.UUID("1e000000-0000-4000-8000-000000000001")
TENANT_BETA = uuid.UUID("1e000000-0000-4000-8000-000000000002")

# (Keycloak user id, tenant, user_type, e-mail, display name). The super admin has no CRM
# user row on purpose: platform users belong to no tenant.
USERS = [
    ("a1000000-0000-4000-8000-000000000001", TENANT_ALPHA, "staff", "admin@alpha.example.test", "Alex Admin"),
    ("a1000000-0000-4000-8000-000000000002", TENANT_ALPHA, "staff", "manager@alpha.example.test", "Morgan Manager"),
    ("a1000000-0000-4000-8000-000000000003", TENANT_ALPHA, "staff", "agent1@alpha.example.test", "Avery Agent"),
    ("a1000000-0000-4000-8000-000000000004", TENANT_ALPHA, "staff", "agent2@alpha.example.test", "Blake Agent"),
    ("a1000000-0000-4000-8000-000000000005", TENANT_ALPHA, "staff", "support@alpha.example.test", "Casey Support"),
    ("a1000000-0000-4000-8000-000000000006", TENANT_ALPHA, "customer", "customer1@customer1.example.test", "Dana Customer"),
    ("a1000000-0000-4000-8000-000000000007", TENANT_ALPHA, "customer", "customer2@customer2.example.test", "Eli Customer"),
    ("b1000000-0000-4000-8000-000000000001", TENANT_BETA, "staff", "admin@beta.example.test", "Robin Admin"),
    ("b1000000-0000-4000-8000-000000000002", TENANT_BETA, "customer", "customer@customer3.example.test", "Sky Customer"),
]  # fmt: skip

# Same roles as in realm-crm.json. The CRM keeps a copy (refreshed at every sign-in) so that,
# for example, a manager can assign a lead to agent2 before agent2 has ever logged in.
ROLES = {
    "a1000000-0000-4000-8000-000000000001": ["tenant_admin"],
    "a1000000-0000-4000-8000-000000000002": ["sales_manager"],
    "a1000000-0000-4000-8000-000000000003": ["sales_agent"],
    "a1000000-0000-4000-8000-000000000004": ["sales_agent"],
    "a1000000-0000-4000-8000-000000000005": ["support_agent"],
    "a1000000-0000-4000-8000-000000000006": ["customer"],
    "a1000000-0000-4000-8000-000000000007": ["customer"],
    "b1000000-0000-4000-8000-000000000001": ["tenant_admin"],
    "b1000000-0000-4000-8000-000000000002": ["customer"],
}

ACCOUNT_A1 = uuid.UUID("ac000000-0000-4000-8000-0000000000a1")
ACCOUNT_A2 = uuid.UUID("ac000000-0000-4000-8000-0000000000a2")
ACCOUNT_B1 = uuid.UUID("ac000000-0000-4000-8000-0000000000b1")

ACCOUNTS = [
    # (id, tenant, name, owner)
    (ACCOUNT_A1, TENANT_ALPHA, "Example Customer One Ltd", "a1000000-0000-4000-8000-000000000003"),
    (ACCOUNT_A2, TENANT_ALPHA, "Example Customer Two Ltd", "a1000000-0000-4000-8000-000000000004"),
    (ACCOUNT_B1, TENANT_BETA, "Example Customer Three Ltd", "b1000000-0000-4000-8000-000000000001"),
]

GRANTS = [
    # (tenant, customer user, account)
    (TENANT_ALPHA, "a1000000-0000-4000-8000-000000000006", ACCOUNT_A1),
    (TENANT_ALPHA, "a1000000-0000-4000-8000-000000000007", ACCOUNT_A2),
    (TENANT_BETA, "b1000000-0000-4000-8000-000000000002", ACCOUNT_B1),
]


# Fictional catalogue for tenant Alpha: a default EUR price book with three products.
PRICE_BOOK_ALPHA = uuid.UUID("9b000000-0000-4000-8000-000000000001")
PRODUCTS = [
    # (id, sku, name, type, unit, tax rate, price in EUR)
    ("9a000000-0000-4000-8000-000000000001", "WID-100", "Demo widget", "product", "each", "19", "49.90"),
    ("9a000000-0000-4000-8000-000000000002", "SVC-INSTALL", "Installation service", "service", "hour", "19", "85.00"),
    ("9a000000-0000-4000-8000-000000000003", "SUB-SUPPORT", "Support subscription", "subscription", "month", "19", "199.00"),
]  # fmt: skip


def _insert_missing(
    connection: Any, table: str, rows: list[dict[str, Any]], key: list[str]
) -> None:
    statement = insert(metadata.tables[table]).on_conflict_do_nothing(index_elements=key)
    connection.execute(statement, rows)


def main() -> None:
    settings = Settings()
    engine = create_engine(MigrationSettings().migration_database_url.get_secret_value())
    with engine.begin() as connection:
        _insert_missing(
            connection,
            "tenants",
            [
                {"id": TENANT_ALPHA, "slug": "alpha-demo", "name": "Alpha Demo (fictional)"},
                {"id": TENANT_BETA, "slug": "beta-demo", "name": "Beta Demo (fictional)"},
            ],
            ["id"],
        )
        users = insert(metadata.tables["users"])
        connection.execute(
            # Insert new users; for existing ones only refresh the role snapshot.
            users.on_conflict_do_update(
                index_elements=["id"], set_={"roles": users.excluded.roles}
            ),
            [
                {
                    "id": uuid.UUID(kc_id),
                    "tenant_id": tenant,
                    "idp_issuer": settings.oidc_issuer,
                    "idp_subject": kc_id,
                    "email": email,
                    "display_name": name,
                    "user_type": user_type,
                    "roles": ROLES[kc_id],
                }
                for kc_id, tenant, user_type, email, name in USERS
            ],
        )
        _insert_missing(
            connection,
            "accounts",
            [
                {"id": a, "tenant_id": t, "name": n, "owner_id": uuid.UUID(o)}
                for a, t, n, o in ACCOUNTS
            ],
            ["id"],
        )
        _insert_missing(
            connection,
            "portal_access_grants",
            [{"tenant_id": t, "user_id": uuid.UUID(u), "account_id": a} for t, u, a in GRANTS],
            ["tenant_id", "user_id", "account_id"],
        )
        _insert_missing(
            connection,
            "products",
            [
                {"id": uuid.UUID(i), "tenant_id": TENANT_ALPHA, "sku": sku, "name": name,
                 "product_type": kind, "unit": unit, "tax_rate": tax}
                for i, sku, name, kind, unit, tax, _ in PRODUCTS
            ],
            ["id"],
        )  # fmt: skip
        _insert_missing(
            connection,
            "price_books",
            [{"id": PRICE_BOOK_ALPHA, "tenant_id": TENANT_ALPHA, "name": "Standard EUR",
              "currency": "EUR", "is_default": True}],
            ["id"],
        )  # fmt: skip
        _insert_missing(
            connection,
            "price_book_entries",
            [
                {"tenant_id": TENANT_ALPHA, "price_book_id": PRICE_BOOK_ALPHA,
                 "product_id": uuid.UUID(i), "unit_price": price}
                for i, *_, price in PRODUCTS
            ],
            ["tenant_id", "price_book_id", "product_id"],
        )  # fmt: skip
        for table in ("tenants", "users", "accounts", "portal_access_grants", "products"):
            total = connection.scalar(select(func.count()).select_from(metadata.tables[table]))
            print(f"{table}: {total} row(s) in database")
    engine.dispose()


if __name__ == "__main__":
    main()
