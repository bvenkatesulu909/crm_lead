"""Buyer memory: what we know about a buyer, each detail a fact or an assumption (ADR 0028, BM1).

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-12

One table, ``buyer_memory_items``: per lead, a key from a fixed list, a short value and a status.
A fact must cite a source and a quote; an assumption must give a reason - the database itself
refuses anything else, so a guess can never be stored as something the buyer said.

Rows are insert-only (a change adds a row; the newest row of a key is the current one). Two locks
against editing: a trigger refuses every UPDATE (it binds every role, the owner too) and the
application role has no UPDATE, DELETE or TRUNCATE privilege. Deleting stays possible only for the
table's owner, which is how an organisation's erasure of a lead would remove its memory.

ENABLE + FORCE row-level security and the one tenant policy (ADR 0009), like every tenant table.
The key, status and source lists are written out here on purpose: a migration must not change
when the application code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = (
    "budget", "property_type", "location", "timeline", "purpose", "financing", "household",
    "decision_makers", "must_haves", "deal_breakers", "current_home", "other_options",
)  # fmt: skip
_SOURCES = ("website_chat", "timeline_entry", "lead_record", "buyer_confirmed")

_CHECKS = (
    ("key_allowed", f"key IN {_KEYS}"),
    ("status_allowed", "status IN ('fact', 'assumption')"),
    ("source_allowed", f"source IS NULL OR source IN {_SOURCES}"),
    ("value_length", "char_length(value) BETWEEN 1 AND 300"),
    ("quote_length", "quote IS NULL OR char_length(quote) BETWEEN 1 AND 300"),
    ("reason_length", "reason IS NULL OR char_length(reason) BETWEEN 1 AND 300"),
    # A fact says where it came from and what the buyer said; it has no "reason".
    ("fact_cites_source", "status <> 'fact' OR (source IS NOT NULL AND quote IS NOT NULL)"),
    ("fact_has_no_reason", "status <> 'fact' OR reason IS NULL"),
    # An assumption says why we think so; it points at no source (that would make it a fact).
    ("assumption_has_reason", "status <> 'assumption' OR reason IS NOT NULL"),
    (
        "assumption_has_no_source",
        "status <> 'assumption' OR (source IS NULL AND quote IS NULL AND source_ref IS NULL)",
    ),
    # Only a timeline entry or a website conversation is pointed at by id.
    (
        "source_ref_matches_source",
        "(source IN ('timeline_entry', 'website_chat')) = (source_ref IS NOT NULL)",
    ),
)


def upgrade() -> None:
    op.create_table(
        "buyer_memory_items",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.Uuid(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *[
            sa.CheckConstraint(condition, name=op.f(f"ck_buyer_memory_items_{name}"))
            for name, condition in _CHECKS
        ],
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name=op.f("fk_buyer_memory_items_tenant_id_lead_id_leads"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recorded_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_buyer_memory_items_tenant_id_recorded_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_buyer_memory_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyer_memory_items")),
    )
    op.create_index(
        "ix_buyer_memory_items_tenant_id_lead_id_seq",
        "buyer_memory_items",
        ["tenant_id", "lead_id", "seq"],
    )

    op.execute("ALTER TABLE buyer_memory_items ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE buyer_memory_items FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY buyer_memory_items_tenant_isolation ON buyer_memory_items
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Lock 1: the trigger, which binds every role including the table's owner.
    op.execute(
        """
        CREATE FUNCTION buyer_memory_items_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'buyer_memory_items rows cannot be changed';
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER buyer_memory_items_guard BEFORE UPDATE ON buyer_memory_items
            FOR EACH ROW EXECUTE FUNCTION buyer_memory_items_guard();
        """
    )
    # Lock 2: the application role has no UPDATE, DELETE or TRUNCATE privilege at all.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'buyer_memory_items'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format(
              'REVOKE UPDATE, DELETE, TRUNCATE ON buyer_memory_items FROM %I', grantee_name
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS buyer_memory_items_guard ON buyer_memory_items;")
    op.execute("DROP FUNCTION IF EXISTS buyer_memory_items_guard();")
    op.execute("DROP POLICY IF EXISTS buyer_memory_items_tenant_isolation ON buyer_memory_items;")
    op.drop_index("ix_buyer_memory_items_tenant_id_lead_id_seq", table_name="buyer_memory_items")
    op.drop_table("buyer_memory_items")
