"""Evidence of the live web check, with tenant-isolation RLS and an insert-only guard (WC2b).

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-30

One table (ADR 0019): ``web_evidence``. It gets ENABLE + FORCE row-level security and the one
tenant policy (ADR 0009), like every tenant table. It is also EVIDENCE, so the database itself
guards it: a trigger refuses every UPDATE, and refuses to delete a row younger than 365 days
(the retention; the worker deletes older rows). The application role also loses UPDATE and
TRUNCATE, so there are two locks, not one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_evidence",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=60), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("body_sha256", sa.String(length=64), nullable=True),
        sa.Column("registered_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("excerpt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "cleaned",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(verdict = 'error') = (error_code IS NOT NULL)",
            name=op.f("ck_web_evidence_error_has_code"),
        ),
        sa.CheckConstraint(
            "body_sha256 IS NULL OR body_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_web_evidence_body_sha256_shape"),
        ),
        sa.CheckConstraint(
            "char_length(excerpt) <= 4096", name=op.f("ck_web_evidence_excerpt_length")
        ),
        sa.CheckConstraint(
            "char_length(query) BETWEEN 1 AND 200", name=op.f("ck_web_evidence_query_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cleaned) = 'array'", name=op.f("ck_web_evidence_cleaned_is_list")
        ),
        sa.CheckConstraint(
            "source_key ~ '^[a-z][a-z0-9_]{2,59}$'", name=op.f("ck_web_evidence_source_key_shape")
        ),
        sa.CheckConstraint(
            "target_type IN ('lead', 'account')", name=op.f("ck_web_evidence_target_type_allowed")
        ),
        sa.CheckConstraint(
            "verdict IN ('found', 'not_found', 'unclear', 'error')",
            name=op.f("ck_web_evidence_verdict_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_web_evidence_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_web_evidence_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_evidence")),
        sa.UniqueConstraint(
            "tenant_id", "request_id", name=op.f("uq_web_evidence_tenant_id_request_id")
        ),
    )
    op.create_index(
        "ix_web_evidence_tenant_id_target",
        "web_evidence",
        ["tenant_id", "target_type", "target_id", "seq"],
    )

    op.execute("ALTER TABLE web_evidence ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE web_evidence FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY web_evidence_tenant_isolation ON web_evidence
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Lock 1: the trigger, which binds every role including the table's owner.
    op.execute(
        """
        CREATE FUNCTION web_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'web_evidence rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'web_evidence rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER web_evidence_guard BEFORE UPDATE OR DELETE ON web_evidence
            FOR EACH ROW EXECUTE FUNCTION web_evidence_guard();
        """
    )
    # Lock 2: the application role has no UPDATE or TRUNCATE privilege at all.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'web_evidence'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON web_evidence FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS web_evidence_guard ON web_evidence;")
    op.execute("DROP FUNCTION IF EXISTS web_evidence_guard();")
    op.execute("DROP POLICY IF EXISTS web_evidence_tenant_isolation ON web_evidence;")
    op.drop_index("ix_web_evidence_tenant_id_target", table_name="web_evidence")
    op.drop_table("web_evidence")
