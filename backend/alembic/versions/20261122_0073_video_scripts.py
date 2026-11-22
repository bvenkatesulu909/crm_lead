"""Saved video scripts (ADR 0041, VB3)

Revision ID: 0073
Revises: 0072
Create Date: 2026-11-22

One new table, ``video_scripts``: a saved version of the script for a lead's buyer video. ENABLE +
FORCE row-level security and the tenant policy (ADR 0009), database checks for every fixed list, and
the two locks the other insert-only tables have (a trigger refuses every UPDATE and a DELETE of a
row younger than 365 days; the application role loses UPDATE and TRUNCATE).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_scripts",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("tone", sa.String(length=20), nullable=False),
        sa.Column("goal", sa.String(length=20), nullable=False),
        sa.Column("length_seconds", sa.Integer(), nullable=False),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("words", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_video_scripts_version_positive")),
        sa.CheckConstraint(
            "language IN ('en', 'hi', 'te')", name=op.f("ck_video_scripts_language_allowed")
        ),
        sa.CheckConstraint(
            "tone IN ('warm', 'professional', 'brisk')", name=op.f("ck_video_scripts_tone_allowed")
        ),
        sa.CheckConstraint(
            "goal IN ('introduce', 'follow_up', 'after_visit', 'explain_quote', 'revive')",
            name=op.f("ck_video_scripts_goal_allowed"),
        ),
        sa.CheckConstraint(
            "length_seconds IN (30, 60, 90)", name=op.f("ck_video_scripts_length_allowed")
        ),
        sa.CheckConstraint(
            "source IN ('hand_written', 'ai_draft')", name=op.f("ck_video_scripts_source_allowed")
        ),
        sa.CheckConstraint("words >= 1", name=op.f("ck_video_scripts_words_positive")),
        sa.CheckConstraint(
            "jsonb_array_length(lines) BETWEEN 1 AND 12", name=op.f("ck_video_scripts_lines_count")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name=op.f("fk_video_scripts_tenant_id_lead_id_leads"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_video_scripts_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_video_scripts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_video_scripts")),
        sa.UniqueConstraint(
            "tenant_id",
            "lead_id",
            "version",
            name=op.f("uq_video_scripts_tenant_id_lead_id_version"),
        ),
    )
    op.create_index(
        "ix_video_scripts_tenant_id_lead_id", "video_scripts", ["tenant_id", "lead_id", "seq"]
    )

    op.execute("ALTER TABLE video_scripts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE video_scripts FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY video_scripts_tenant_isolation ON video_scripts
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    op.execute(
        """
        CREATE FUNCTION video_scripts_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'video_scripts rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'video_scripts rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER video_scripts_guard BEFORE UPDATE OR DELETE ON video_scripts
            FOR EACH ROW EXECUTE FUNCTION video_scripts_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'video_scripts'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON video_scripts FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS video_scripts_guard ON video_scripts;")
    op.execute("DROP FUNCTION IF EXISTS video_scripts_guard();")
    op.execute("DROP POLICY IF EXISTS video_scripts_tenant_isolation ON video_scripts;")
    op.drop_index("ix_video_scripts_tenant_id_lead_id", table_name="video_scripts")
    op.drop_table("video_scripts")
