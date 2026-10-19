"""Lead management: opportunities, lead timeline, assignment history, audit log.

1. users.roles: last-known CRM roles (refreshed at sign-in), used to validate lead assignees.
2. opportunities: minimal table so lead conversion can create one.
3. leads.converted_opportunity_id + rule "a converted lead points at its account and contact".
4. lead_activities: the lead's timeline (calls, notes, ... and automatic events).
5. lead_assignments: who owned the lead, when, who changed it and why.
6. audit_log: who changed what, before -> after.

audit_log and lead_assignments are append-only for the application: UPDATE, DELETE and
TRUNCATE are revoked from every role except the schema owner.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _now(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _event_time(name: str) -> sa.Column[Any]:
    # Real insert time, not transaction start (see LeadActivity.occurred_at).
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False
    )


def _seq() -> sa.Column[Any]:
    return sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"], name=f"fk_{table}_tenant_id_tenants", ondelete="RESTRICT"
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        ["users.tenant_id", "users.id"],
        name=f"fk_{table}_tenant_id_{column}_users",
        ondelete="RESTRICT",
    )


_APPEND_ONLY_TABLES = frozenset({"audit_log", "lead_assignments"})


def _make_append_only(table: str) -> None:
    # Default privileges (see the PostgreSQL init script) gave the app role full DML on new
    # tables. Take UPDATE/DELETE/TRUNCATE away again from everyone except the owner.
    # The table name is a constant from this file (checked below), never user input.
    if table not in _APPEND_ONLY_TABLES:
        raise ValueError(f"unexpected table {table!r}")
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = '{table}'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM %I', grantee_name);
          END LOOP;
        END $$;
        """  # noqa: S608
    )


def upgrade() -> None:
    # 1. Role snapshot on users.
    op.add_column(
        "users",
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(30)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )

    # 2. Opportunities.
    op.create_table(
        "opportunities",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("primary_contact_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(30), server_default=sa.text("'prospecting'"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_opportunities"),
        _tenant_fk("opportunities"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_opportunities_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_opportunities_tenant_id_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "primary_contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            name="fk_opportunities_tenant_id_primary_contact_id_contacts",
            ondelete="RESTRICT",
        ),
        _user_fk("opportunities", "owner_id"),
        sa.CheckConstraint(
            "stage IN ('prospecting', 'qualification', 'proposal', 'negotiation', "
            "'closed_won', 'closed_lost')",
            name=op.f("ck_opportunities_stage_allowed"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0", name=op.f("ck_opportunities_amount_not_negative")
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_opportunities_currency_iso")),
    )
    op.create_index(
        "ix_opportunities_tenant_id_account_id", "opportunities", ["tenant_id", "account_id"]
    )
    op.create_index(
        "ix_opportunities_tenant_id_owner_id", "opportunities", ["tenant_id", "owner_id"]
    )

    # 3. Leads: link to the opportunity created by conversion; stricter conversion rule.
    op.add_column("leads", sa.Column("converted_opportunity_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_leads_tenant_id_converted_opportunity_id_opportunities",
        "leads",
        "opportunities",
        ["tenant_id", "converted_opportunity_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_leads_converted_has_records"),
        "leads",
        "status <> 'converted' OR "
        "(converted_account_id IS NOT NULL AND converted_contact_id IS NOT NULL)",
    )

    # 4. Lead timeline.
    op.create_table(
        "lead_activities",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        _event_time("occurred_at"),
        _seq(),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        _now("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_lead_activities"),
        _tenant_fk("lead_activities"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name="fk_lead_activities_tenant_id_lead_id_leads",
            ondelete="RESTRICT",
        ),
        _user_fk("lead_activities", "actor_user_id"),
        sa.CheckConstraint(
            "kind IN ('note', 'call', 'email', 'meeting', "
            "'created', 'status_changed', 'assigned', 'converted')",
            name=op.f("ck_lead_activities_kind_allowed"),
        ),
    )
    op.create_index(
        "ix_lead_activities_tenant_id_lead_id_occurred_at",
        "lead_activities",
        ["tenant_id", "lead_id", "occurred_at"],
    )

    # 5. Assignment history (append-only).
    op.create_table(
        "lead_assignments",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("from_user_id", sa.Uuid(), nullable=True),
        sa.Column("to_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        _event_time("assigned_at"),
        _seq(),
        sa.PrimaryKeyConstraint("id", name="pk_lead_assignments"),
        _tenant_fk("lead_assignments"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name="fk_lead_assignments_tenant_id_lead_id_leads",
            ondelete="RESTRICT",
        ),
        _user_fk("lead_assignments", "from_user_id"),
        _user_fk("lead_assignments", "to_user_id"),
        _user_fk("lead_assignments", "assigned_by_user_id"),
    )
    op.create_index(
        "ix_lead_assignments_tenant_id_lead_id_assigned_at",
        "lead_assignments",
        ["tenant_id", "lead_id", "assigned_at"],
    )
    _make_append_only("lead_assignments")

    # 6. Audit log (append-only).
    op.create_table(
        "audit_log",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        _event_time("occurred_at"),
        _seq(),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        _tenant_fk("audit_log"),
        _user_fk("audit_log", "actor_user_id"),
    )
    op.create_index(
        "ix_audit_log_tenant_id_entity_type_entity_id_occurred_at",
        "audit_log",
        ["tenant_id", "entity_type", "entity_id", "occurred_at"],
    )
    _make_append_only("audit_log")


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("lead_assignments")
    op.drop_table("lead_activities")
    op.drop_constraint(op.f("ck_leads_converted_has_records"), "leads", type_="check")
    op.drop_constraint(
        "fk_leads_tenant_id_converted_opportunity_id_opportunities", "leads", type_="foreignkey"
    )
    op.drop_column("leads", "converted_opportunity_id")
    op.drop_table("opportunities")
    op.drop_column("users", "roles")
