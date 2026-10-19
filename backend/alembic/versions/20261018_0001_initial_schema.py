"""Initial schema: tenants, users, accounts, contacts, leads.

Every table except ``tenants`` has ``tenant_id``. References between tenant-owned tables are
composite foreign keys ``(tenant_id, x_id) -> table(tenant_id, id)``, so PostgreSQL itself
rejects any link between records of different tenants.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_column() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _tenant_column() -> sa.Column[Any]:
    return sa.Column("tenant_id", sa.Uuid(), nullable=False)


def _timestamp_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _business_record_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"], name=f"fk_{table}_tenant_id_tenants", ondelete="RESTRICT"
    )


def upgrade() -> None:
    # --- tenants: the companies using the CRM. Root of all ownership. -----------------------
    op.create_table(
        "tenants",
        _id_column(),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.CheckConstraint(
            r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_tenants_slug_format")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name=op.f("ck_tenants_status_allowed")
        ),
    )

    # --- users: maps a Keycloak identity (issuer + subject) to a CRM user in one tenant. ---
    op.create_table(
        "users",
        _id_column(),
        _tenant_column(),
        sa.Column("idp_issuer", sa.String(255), nullable=False),
        sa.Column("idp_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("user_type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        _tenant_fk("users"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idp_issuer",
            "idp_subject",
            name="uq_users_tenant_id_idp_issuer_idp_subject",
        ),
        sa.CheckConstraint(
            "user_type IN ('staff', 'customer')", name=op.f("ck_users_user_type_allowed")
        ),
    )
    op.create_index(
        "uq_users_tenant_id_lower_email",
        "users",
        ["tenant_id", sa.literal_column("lower(email)")],
        unique=True,
    )

    # --- accounts: customer organisations of a tenant. ----------------------------------
    op.create_table(
        "accounts",
        _id_column(),
        _tenant_column(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_number", sa.String(50), nullable=True),
        sa.Column("website", sa.String(2048), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("parent_account_id", sa.Uuid(), nullable=True),
        *_timestamp_columns(),
        *_business_record_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        _tenant_fk("accounts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_accounts_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "account_number", name="uq_accounts_tenant_id_account_number"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_accounts_tenant_id_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_accounts_tenant_id_parent_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "parent_account_id IS NULL OR parent_account_id <> id",
            name=op.f("ck_accounts_not_own_parent"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name=op.f("ck_accounts_status_allowed")
        ),
    )
    op.create_index(
        "ix_accounts_tenant_id_lower_name",
        "accounts",
        ["tenant_id", sa.literal_column("lower(name)")],
    )
    op.create_index("ix_accounts_tenant_id_owner_id", "accounts", ["tenant_id", "owner_id"])
    op.create_index(
        "ix_accounts_tenant_id_parent_account_id", "accounts", ["tenant_id", "parent_account_id"]
    )

    # --- contacts: people, usually at a customer account. -------------------------------
    op.create_table(
        "contacts",
        _id_column(),
        _tenant_column(),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("job_title", sa.String(150), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        *_timestamp_columns(),
        *_business_record_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
        _tenant_fk("contacts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_contacts_tenant_id_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_contacts_tenant_id_owner_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_contacts_tenant_id_account_id", "contacts", ["tenant_id", "account_id"])
    op.create_index("ix_contacts_tenant_id_owner_id", "contacts", ["tenant_id", "owner_id"])
    op.create_index(
        "ix_contacts_tenant_id_lower_email",
        "contacts",
        ["tenant_id", sa.literal_column("lower(email)")],
    )
    op.create_index(
        "ix_contacts_tenant_id_last_name_first_name",
        "contacts",
        ["tenant_id", "last_name", "first_name"],
    )

    # --- leads: potential customers; conversion links them to an account + contact. ------
    op.create_table(
        "leads",
        _id_column(),
        _tenant_column(),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("job_title", sa.String(150), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'new'"), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_account_id", sa.Uuid(), nullable=True),
        sa.Column("converted_contact_id", sa.Uuid(), nullable=True),
        *_timestamp_columns(),
        *_business_record_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_leads"),
        _tenant_fk("leads"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_leads_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_leads_tenant_id_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "converted_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_leads_tenant_id_converted_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "converted_contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            name="fk_leads_tenant_id_converted_contact_id_contacts",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'contacted', 'qualified', 'unqualified', 'converted')",
            name=op.f("ck_leads_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status = 'converted') = (converted_at IS NOT NULL)",
            name=op.f("ck_leads_converted_consistent"),
        ),
    )
    op.create_index("ix_leads_tenant_id_status", "leads", ["tenant_id", "status"])
    op.create_index("ix_leads_tenant_id_owner_id", "leads", ["tenant_id", "owner_id"])
    op.create_index(
        "ix_leads_tenant_id_lower_email", "leads", ["tenant_id", sa.literal_column("lower(email)")]
    )
    op.create_index("ix_leads_tenant_id_created_at", "leads", ["tenant_id", "created_at"])


def downgrade() -> None:
    # Reverse dependency order: tables that reference others are dropped first.
    # Dropping a table also drops its indexes and constraints.
    op.drop_table("leads")
    op.drop_table("contacts")
    op.drop_table("accounts")
    op.drop_table("users")
    op.drop_table("tenants")
