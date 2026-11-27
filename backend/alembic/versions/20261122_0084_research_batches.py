"""Batch account research: batches and their items (ADR 0042, BR1).

Revision ID: 0084
Revises: 0083
Create Date: 2026-11-22

Two tenant tables, ENABLE + FORCE row-level security and the tenant policy on both (ADR 0009).
They are append-mostly: a trigger refuses to change the columns that decide what a batch may do
(starter, source, account list, positions, the confirmed estimate and the cap) and refuses to delete
a row younger than 365 days; the application role loses TRUNCATE. The lists of states and failure
reasons are written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH_STATUSES = "'running', 'finished', 'cancelled', 'stopped_budget'"
ITEM_STATUSES = "'queued', 'running', 'done', 'reused', 'skipped', 'failed', 'not_run'"
FAILURE_CODES = (
    "'no_sourced_sentence', 'answer_refused', 'unavailable', 'over_budget', 'not_readable', "
    "'rate_limited', 'error'"
)


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def upgrade() -> None:
    op.create_table(
        "research_batches",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'running'"), nullable=False
        ),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("saved_filter_id", sa.Uuid(), nullable=True),
        sa.Column("account_count", sa.Integer(), nullable=False),
        sa.Column("not_available_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("archived_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("estimated_upper_tokens", sa.BigInteger(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("token_cap", sa.BigInteger(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("research_again", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            f"status IN ({BATCH_STATUSES})", name=op.f("ck_research_batches_status_allowed")
        ),
        sa.CheckConstraint(
            "source IN ('filter', 'rows')", name=op.f("ck_research_batches_source_allowed")
        ),
        sa.CheckConstraint(
            "account_count BETWEEN 1 AND 100", name=op.f("ck_research_batches_account_count_range")
        ),
        sa.CheckConstraint(
            "token_cap >= 0 AND tokens_used >= 0",
            name=op.f("ck_research_batches_tokens_not_negative"),
        ),
        sa.CheckConstraint(
            "estimated_upper_tokens >= 0", name=op.f("ck_research_batches_estimate_not_negative")
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_research_batches_finished_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_research_batches_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_research_batches_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_batches")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_research_batches_tenant_id_id")),
    )
    op.create_index(
        "ix_research_batches_tenant_id_created_by_user_id",
        "research_batches",
        ["tenant_id", "created_by_user_id"],
    )
    op.create_index(
        "ix_research_batches_tenant_id_status", "research_batches", ["tenant_id", "status"]
    )
    _tenant_policy("research_batches")

    op.create_table(
        "research_batch_items",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("failure_code", sa.String(length=30), nullable=True),
        sa.Column("brief_id", sa.Uuid(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"status IN ({ITEM_STATUSES})", name=op.f("ck_research_batch_items_status_allowed")
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 100", name=op.f("ck_research_batch_items_position_range")
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL) AND "
            f"(failure_code IS NULL OR failure_code IN ({FAILURE_CODES}))",
            name=op.f("ck_research_batch_items_failure_matches_status"),
        ),
        sa.CheckConstraint(
            "(brief_id IS NOT NULL) = (status IN ('done', 'reused'))",
            name=op.f("ck_research_batch_items_brief_matches_status"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_research_batch_items_tokens_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["research_batches.tenant_id", "research_batches.id"],
            name=op.f("fk_research_batch_items_tenant_id_batch_id_research_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name=op.f("fk_research_batch_items_tenant_id_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_research_batch_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_batch_items")),
        sa.UniqueConstraint(
            "batch_id", "position", name=op.f("uq_research_batch_items_batch_id_position")
        ),
        sa.UniqueConstraint(
            "batch_id", "account_id", name=op.f("uq_research_batch_items_batch_id_account_id")
        ),
    )
    op.create_index(
        "ix_research_batch_items_tenant_id_batch_id",
        "research_batch_items",
        ["tenant_id", "batch_id", "position"],
    )
    _tenant_policy("research_batch_items")

    op.execute(
        """
        CREATE FUNCTION research_batches_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.created_at > now() - interval '365 days' THEN
              RAISE EXCEPTION '% rows can be deleted only after 365 days', TG_TABLE_NAME;
            END IF;
            RETURN OLD;
          END IF;
          IF TG_TABLE_NAME = 'research_batches' THEN
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.saved_filter_id IS DISTINCT FROM OLD.saved_filter_id
               OR NEW.account_count IS DISTINCT FROM OLD.account_count
               OR NEW.not_available_count IS DISTINCT FROM OLD.not_available_count
               OR NEW.archived_count IS DISTINCT FROM OLD.archived_count
               OR NEW.estimated_upper_tokens IS DISTINCT FROM OLD.estimated_upper_tokens
               OR NEW.estimated_cost_usd IS DISTINCT FROM OLD.estimated_cost_usd
               OR NEW.token_cap IS DISTINCT FROM OLD.token_cap
               OR NEW.research_again IS DISTINCT FROM OLD.research_again THEN
              RAISE EXCEPTION 'these research_batches columns cannot be changed';
            END IF;
            IF NEW.tokens_used < OLD.tokens_used THEN
              RAISE EXCEPTION 'tokens_used can only grow';
            END IF;
            IF OLD.status <> 'running' AND NEW.status IS DISTINCT FROM OLD.status THEN
              RAISE EXCEPTION 'a finished batch cannot change its state';
            END IF;
          ELSE
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.batch_id IS DISTINCT FROM OLD.batch_id
               OR NEW.position IS DISTINCT FROM OLD.position
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
              RAISE EXCEPTION 'these research_batch_items columns cannot be changed';
            END IF;
            IF OLD.status IN ('done', 'reused', 'skipped', 'failed', 'not_run')
               AND NEW.status IS DISTINCT FROM OLD.status THEN
              RAISE EXCEPTION 'a finished item cannot change its state';
            END IF;
          END IF;
          RETURN NEW;
        END
        $$;
        """
    )
    for table in ("research_batches", "research_batch_items"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION research_batches_guard();
            """
        )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text; tbl text;
        BEGIN
          FOREACH tbl IN ARRAY ARRAY['research_batches', 'research_batch_items'] LOOP
            FOR grantee_name IN
              SELECT DISTINCT grantee FROM information_schema.role_table_grants
              WHERE table_schema = current_schema()
                AND information_schema.role_table_grants.table_name = tbl
                AND privilege_type = 'TRUNCATE' AND grantee <> current_user
            LOOP
              EXECUTE format('REVOKE TRUNCATE ON %I FROM %I', tbl, grantee_name);
            END LOOP;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    for table in ("research_batch_items", "research_batches"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_guard ON {table};")
    op.execute("DROP FUNCTION IF EXISTS research_batches_guard();")
    op.execute(
        "DROP POLICY IF EXISTS research_batch_items_tenant_isolation ON research_batch_items;"
    )
    op.drop_index("ix_research_batch_items_tenant_id_batch_id", table_name="research_batch_items")
    op.drop_table("research_batch_items")
    op.execute("DROP POLICY IF EXISTS research_batches_tenant_isolation ON research_batches;")
    op.drop_index("ix_research_batches_tenant_id_status", table_name="research_batches")
    op.drop_index("ix_research_batches_tenant_id_created_by_user_id", table_name="research_batches")
    op.drop_table("research_batches")
