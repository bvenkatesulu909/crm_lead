"""Support tickets: tickets, ticket comments, per-tenant ticket numbers.

- tickets: belongs to a customer account (same tenant, composite FK); status, priority,
  channel (portal / staff / assistant handoff), assignee, SLA deadlines.
- ticket_comments: public replies and internal notes. Append-only for the application
  (UPDATE / DELETE / TRUNCATE revoked from every role except the schema owner).
- ticket_number_counters: last ticket number per tenant (T-0001, T-0002, ...).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, *, nullable: bool = False, default: Any = None) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=default, nullable=nullable)


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        ["users.tenant_id", "users.id"],
        name=f"fk_{table}_tenant_id_{column}_users",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "ticket_number_counters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_ticket_number_counters"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_ticket_number_counters_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'new'"), nullable=False),
        sa.Column("priority", sa.String(10), server_default=sa.text("'normal'"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        _ts("first_response_due_at"),
        _ts("resolution_due_at"),
        _ts("first_responded_at", nullable=True),
        _ts("resolved_at", nullable=True),
        _ts("closed_at", nullable=True),
        _ts("created_at", default=sa.func.now()),
        _ts("updated_at", default=sa.func.now()),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tickets_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tickets_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_tickets_tenant_id_number"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_tickets_tenant_id_account_id_accounts",
            ondelete="RESTRICT",
        ),
        _user_fk("tickets", "requester_user_id"),
        _user_fk("tickets", "assignee_user_id"),
        sa.CheckConstraint(
            "status IN ('new', 'open', 'pending_customer', 'resolved', 'closed')",
            name=op.f("ck_tickets_status_allowed"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name=op.f("ck_tickets_priority_allowed"),
        ),
        sa.CheckConstraint(
            "channel IN ('portal', 'staff', 'assistant')", name=op.f("ck_tickets_channel_allowed")
        ),
        sa.CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL)",
            name=op.f("ck_tickets_closed_consistent"),
        ),
        sa.CheckConstraint("number > 0", name=op.f("ck_tickets_number_positive")),
    )
    op.create_index("ix_tickets_tenant_id_status", "tickets", ["tenant_id", "status"])
    op.create_index("ix_tickets_tenant_id_account_id", "tickets", ["tenant_id", "account_id"])
    op.create_index(
        "ix_tickets_tenant_id_assignee_user_id", "tickets", ["tenant_id", "assignee_user_id"]
    )
    op.create_index("ix_tickets_tenant_id_created_at", "tickets", ["tenant_id", "created_at"])

    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(10), nullable=False),
        _ts("created_at", default=sa.func.clock_timestamp()),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ticket_comments"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_ticket_comments_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ticket_id"],
            ["tickets.tenant_id", "tickets.id"],
            name="fk_ticket_comments_tenant_id_ticket_id_tickets",
            ondelete="RESTRICT",
        ),
        _user_fk("ticket_comments", "author_user_id"),
        sa.CheckConstraint(
            "visibility IN ('public', 'internal')",
            name=op.f("ck_ticket_comments_visibility_allowed"),
        ),
    )
    op.create_index(
        "ix_ticket_comments_tenant_id_ticket_id_seq",
        "ticket_comments",
        ["tenant_id", "ticket_id", "seq"],
    )
    # Comments are a record of what was said: the application may add, never rewrite.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'ticket_comments'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format(
              'REVOKE UPDATE, DELETE, TRUNCATE ON ticket_comments FROM %I', grantee_name
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("ticket_comments")
    op.drop_table("tickets")
    op.drop_table("ticket_number_counters")
