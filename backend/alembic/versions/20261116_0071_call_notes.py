"""Call notes and the deal checklist (ADR 0035, CN1).

Revision ID: 0071
Revises: 0070
Create Date: 2026-11-16

Three new tables. ``call_notes`` is one drafted note for a call recording (which checklist frame,
which version, how many claims were turned into unknown). ``call_note_lines`` holds its lines; the
database itself keeps the three states apart: a *stated* line has a value, a quote and its time, an
*assumed* line also has a reason, an *unknown* line has nothing but a code. ``call_note_settings``
holds the organisation's choice of frame (BANT or MEDDIC).

ENABLE + FORCE row-level security and the tenant policy on all three (ADR 0009). The two note tables
are insert-only: a trigger refuses every UPDATE and a DELETE of a row younger than 365 days, and the
application role loses UPDATE and TRUNCATE on them.

The list of fields is written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIELDS = (
    "'note', 'budget', 'authority', 'need', 'timeline', 'metrics', 'economic_buyer', "
    "'decision_criteria', 'decision_process', 'identify_pain', 'champion'"
)
FRAMEWORKS = "'bant', 'meddic'"
PARTS = "value IS NOT NULL AND quote IS NOT NULL AND start_ms IS NOT NULL AND end_ms IS NOT NULL"


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


def _id_and_tenant() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "call_notes",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("framework", sa.String(length=10), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=60), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("downgraded", sa.Integer(), nullable=False),
        sa.Column("dropped_notes", sa.Integer(), nullable=False),
        sa.Column("cleaned_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_id_and_tenant(),
        sa.CheckConstraint(
            f"framework IN ({FRAMEWORKS})", name=op.f("ck_call_notes_framework_allowed")
        ),
        sa.CheckConstraint("version_no >= 1", name=op.f("ck_call_notes_version_positive")),
        sa.CheckConstraint(
            "char_length(model_name) BETWEEN 1 AND 60", name=op.f("ck_call_notes_model_name_length")
        ),
        sa.CheckConstraint(
            "tokens >= 0 AND downgraded >= 0 AND dropped_notes >= 0",
            name=op.f("ck_call_notes_counts"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cleaned_codes) = 'array'",
            name=op.f("ck_call_notes_cleaned_codes_is_list"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recording_id"],
            ["call_recordings.tenant_id", "call_recordings.id"],
            name=op.f("fk_call_notes_tenant_id_recording_id_call_recordings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name=op.f("fk_call_notes_tenant_id_lead_id_leads"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_call_notes_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_call_notes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_notes")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_call_notes_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "recording_id",
            "version_no",
            name=op.f("uq_call_notes_tenant_id_recording_id_version_no"),
        ),
    )
    op.create_index(
        "ix_call_notes_tenant_id_recording_id", "call_notes", ["tenant_id", "recording_id"]
    )
    _tenant_policy("call_notes")

    op.create_table(
        "call_note_lines",
        sa.Column("call_note_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("note_code", sa.String(length=40), nullable=True),
        *_id_and_tenant(),
        sa.CheckConstraint("position >= 1", name=op.f("ck_call_note_lines_position_positive")),
        sa.CheckConstraint(f"field IN ({FIELDS})", name=op.f("ck_call_note_lines_field_allowed")),
        sa.CheckConstraint(
            "state IN ('stated', 'assumed', 'unknown')",
            name=op.f("ck_call_note_lines_state_allowed"),
        ),
        sa.CheckConstraint(
            "(state = 'unknown' AND value IS NULL AND quote IS NULL AND start_ms IS NULL "
            "AND end_ms IS NULL AND reason IS NULL) "
            f"OR (state = 'stated' AND {PARTS} AND reason IS NULL) "
            f"OR (state = 'assumed' AND {PARTS} AND reason IS NOT NULL)",
            name=op.f("ck_call_note_lines_shape_by_state"),
        ),
        sa.CheckConstraint(
            "field <> 'note' OR state = 'stated'", name=op.f("ck_call_note_lines_note_is_stated")
        ),
        sa.CheckConstraint(
            "start_ms IS NULL OR (start_ms >= 0 AND end_ms > start_ms "
            "AND end_ms - start_ms <= 300000)",
            name=op.f("ck_call_note_lines_time_window"),
        ),
        sa.CheckConstraint(
            "value IS NULL OR char_length(value) BETWEEN 1 AND "
            "CASE WHEN field = 'note' THEN 200 ELSE 150 END",
            name=op.f("ck_call_note_lines_value_length"),
        ),
        sa.CheckConstraint(
            "quote IS NULL OR char_length(quote) BETWEEN 1 AND 300",
            name=op.f("ck_call_note_lines_quote_length"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) BETWEEN 1 AND 300",
            name=op.f("ck_call_note_lines_reason_length"),
        ),
        sa.CheckConstraint(
            "note_code IS NULL OR (state = 'unknown' AND note_code ~ '^[a-z_]{1,40}$')",
            name=op.f("ck_call_note_lines_note_code_on_unknown"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_note_id"],
            ["call_notes.tenant_id", "call_notes.id"],
            name=op.f("fk_call_note_lines_tenant_id_call_note_id_call_notes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_call_note_lines_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_note_lines")),
        sa.UniqueConstraint(
            "tenant_id",
            "call_note_id",
            "position",
            name=op.f("uq_call_note_lines_tenant_id_call_note_id_position"),
        ),
    )
    op.create_index(
        "uq_call_note_lines_tenant_id_call_note_id_field",
        "call_note_lines",
        ["tenant_id", "call_note_id", "field"],
        unique=True,
        postgresql_where=sa.text("field <> 'note'"),
    )
    _tenant_policy("call_note_lines")

    op.create_table(
        "call_note_settings",
        sa.Column("framework", sa.String(length=10), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
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
        *_id_and_tenant(),
        sa.CheckConstraint(
            f"framework IN ({FRAMEWORKS})", name=op.f("ck_call_note_settings_framework_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_call_note_settings_tenant_id_updated_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_call_note_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_note_settings")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_call_note_settings_tenant_id")),
    )
    _tenant_policy("call_note_settings")

    op.execute(
        """
        CREATE FUNCTION call_notes_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION '% rows cannot be changed', TG_TABLE_NAME;
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION '% rows can be deleted only after 365 days', TG_TABLE_NAME;
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    # Lines carry no timestamp of their own: they follow their note's age.
    op.execute(
        """
        CREATE FUNCTION call_note_lines_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION '% rows cannot be changed', TG_TABLE_NAME;
          END IF;
          IF EXISTS (
            SELECT 1 FROM call_notes n
            WHERE n.id = OLD.call_note_id AND n.tenant_id = OLD.tenant_id
              AND n.created_at > now() - interval '365 days'
          ) THEN
            RAISE EXCEPTION '% rows can be deleted only after 365 days', TG_TABLE_NAME;
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER call_notes_guard BEFORE UPDATE OR DELETE ON call_notes
            FOR EACH ROW EXECUTE FUNCTION call_notes_guard();
        """
    )
    op.execute(
        """
        CREATE TRIGGER call_note_lines_guard BEFORE UPDATE OR DELETE ON call_note_lines
            FOR EACH ROW EXECUTE FUNCTION call_note_lines_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text; table_name_ text;
        BEGIN
          FOREACH table_name_ IN ARRAY ARRAY['call_notes', 'call_note_lines'] LOOP
            FOR grantee_name IN
              SELECT DISTINCT grantee FROM information_schema.role_table_grants
              WHERE table_schema = current_schema() AND table_name = table_name_
                AND privilege_type IN ('UPDATE', 'TRUNCATE')
                AND grantee <> current_user
            LOOP
              EXECUTE format('REVOKE UPDATE, TRUNCATE ON %I FROM %I', table_name_, grantee_name);
            END LOOP;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS call_note_lines_guard ON call_note_lines;")
    op.execute("DROP TRIGGER IF EXISTS call_notes_guard ON call_notes;")
    op.execute("DROP FUNCTION IF EXISTS call_note_lines_guard();")
    op.execute("DROP FUNCTION IF EXISTS call_notes_guard();")
    for table in ("call_note_settings", "call_note_lines", "call_notes"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_table("call_note_settings")
    op.drop_index("uq_call_note_lines_tenant_id_call_note_id_field", table_name="call_note_lines")
    op.drop_table("call_note_lines")
    op.drop_index("ix_call_notes_tenant_id_recording_id", table_name="call_notes")
    op.drop_table("call_notes")
