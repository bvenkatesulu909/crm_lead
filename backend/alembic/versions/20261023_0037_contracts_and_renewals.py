"""Contracts and renewals: tables, tenant-isolation RLS and an insert-only history (step C1).

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-23

Three tables (see docs/contracts.md): ``contracts``, ``contract_events`` and
``contract_number_counters``. Each gets ENABLE + FORCE row-level security and one tenant policy
(ADR 0009), like every tenant table; the guard test fails a tenant table without it.
``contract_events`` is the history, so the application may only insert into it.

Only the contract tables are created here. (Alembic's automatic comparison also proposed
dropping the knowledge-base tables because those models are not in ``model_registry``; that
is unrelated and deliberately NOT part of this migration.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("contracts", "contract_events", "contract_number_counters")


def upgrade() -> None:
    op.create_table(
        "contract_number_counters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_contract_number_counters_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_contract_number_counters")),
    )
    op.create_table(
        "contracts",
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("quote_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("renewed_from_id", sa.Uuid(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "renewal_notice_days", sa.Integer(), server_default=sa.text("30"), nullable=False
        ),
        sa.Column("renewal_term_months", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'EUR'"), nullable=False),
        sa.Column(
            "total_value",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "billing_frequency",
            sa.String(length=20),
            server_default=sa.text("'annually'"),
            nullable=False,
        ),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termination_reason", sa.String(length=500), nullable=True),
        sa.Column("renewal_reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(status = 'terminated') = (terminated_at IS NOT NULL)",
            name=op.f("ck_contracts_terminated_has_date"),
        ),
        sa.CheckConstraint(
            "billing_frequency IN ('one_time', 'monthly', 'quarterly', 'annually')",
            name=op.f("ck_contracts_billing_allowed"),
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_contracts_currency_iso")),
        sa.CheckConstraint(
            "status <> 'terminated' OR termination_reason IS NOT NULL",
            name=op.f("ck_contracts_terminated_has_reason"),
        ),
        sa.CheckConstraint(
            "status = 'draft' OR (start_date IS NOT NULL AND end_date IS NOT NULL)",
            name=op.f("ck_contracts_dates_when_not_draft"),
        ),
        sa.CheckConstraint(
            "status = 'terminated' OR termination_reason IS NULL",
            name=op.f("ck_contracts_reason_only_if_terminated"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'expired', 'terminated', 'renewed')",
            name=op.f("ck_contracts_status_allowed"),
        ),
        sa.CheckConstraint(
            "renewal_notice_days >= 0 AND renewal_notice_days <= 365",
            name=op.f("ck_contracts_notice_days_range"),
        ),
        sa.CheckConstraint(
            "renewal_term_months IS NULL "
            "OR (renewal_term_months >= 1 AND renewal_term_months <= 120)",
            name=op.f("ck_contracts_renewal_term_range"),
        ),
        sa.CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_contracts_dates_in_order"),
        ),
        sa.CheckConstraint("total_value >= 0", name=op.f("ck_contracts_value_not_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name=op.f("fk_contracts_tenant_id_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            name=op.f("fk_contracts_tenant_id_contact_id_contacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_contracts_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            name=op.f("fk_contracts_tenant_id_opportunity_id_opportunities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_contracts_tenant_id_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name=op.f("fk_contracts_tenant_id_quote_id_quotes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "renewed_from_id"],
            ["contracts.tenant_id", "contracts.id"],
            name=op.f("fk_contracts_tenant_id_renewed_from_id_contracts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_contracts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contracts")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_contracts_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "number", name=op.f("uq_contracts_tenant_id_number")),
    )
    op.create_index(
        "ix_contracts_tenant_id_account_id", "contracts", ["tenant_id", "account_id"], unique=False
    )
    op.create_index(
        "ix_contracts_tenant_id_end_date", "contracts", ["tenant_id", "end_date"], unique=False
    )
    op.create_index(
        "ix_contracts_tenant_id_owner_id", "contracts", ["tenant_id", "owner_id"], unique=False
    )
    op.create_index(
        "ix_contracts_tenant_id_status", "contracts", ["tenant_id", "status"], unique=False
    )
    op.create_table(
        "contract_events",
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'status_changed', 'note', 'renewal_reminder', 'expired')",
            name=op.f("ck_contract_events_event_type_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_contract_events_tenant_id_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name=op.f("fk_contract_events_tenant_id_contract_id_contracts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_contract_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contract_events")),
    )
    op.create_index(
        "ix_contract_events_tenant_id_contract_id",
        "contract_events",
        ["tenant_id", "contract_id"],
        unique=False,
    )

    # Row-level security: the same expression for USING and WITH CHECK; an unset app.tenant_id
    # gives no rows and rejects inserts (fail closed). The table names are fixed identifiers.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id = crm_current_tenant())
                WITH CHECK (tenant_id = crm_current_tenant());
            """
        )
    # The history is insert-only for the application (like the audit log and quote_events).
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'contract_events'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format(
              'REVOKE UPDATE, DELETE, TRUNCATE ON contract_events FROM %I', grantee_name
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_index("ix_contract_events_tenant_id_contract_id", table_name="contract_events")
    op.drop_table("contract_events")
    op.drop_index("ix_contracts_tenant_id_status", table_name="contracts")
    op.drop_index("ix_contracts_tenant_id_owner_id", table_name="contracts")
    op.drop_index("ix_contracts_tenant_id_end_date", table_name="contracts")
    op.drop_index("ix_contracts_tenant_id_account_id", table_name="contracts")
    op.drop_table("contracts")
    op.drop_table("contract_number_counters")
