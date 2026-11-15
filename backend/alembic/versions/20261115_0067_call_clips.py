"""Highlight clips of call recordings (ADR 0033, CL1).

Revision ID: 0067
Revises: 0066
Create Date: 2026-11-15

One new table, ``call_clips``: a short piece of a recorded call with a title, a note, the transcript
lines inside the range and the key of its small audio file. ENABLE + FORCE row-level security
and the tenant policy (ADR 0009). The database refuses a clip shorter than 3 or longer than 120
seconds, an empty title, a ``ready`` clip without its file, a ``failed`` clip without a reason, and
(by trigger) any change to the range, the excerpt, the maker, the recording or the time it was made: only the
title, the note and the file / status fields can change.

``call_recordings`` also gets a unique (tenant, id) pair so a clip's foreign key can name the
organisation as well (a clip can never point at another organisation's recording).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_call_recordings_tenant_id_id"), "call_recordings", ["tenant_id", "id"]
    )
    op.create_table(
        "call_clips",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("made_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("excerpt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("clip_key", sa.Text(), nullable=True),
        sa.Column("audio_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms - start_ms BETWEEN 3000 AND 120000",
            name=op.f("ck_call_clips_range_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'ready', 'failed')", name=op.f("ck_call_clips_status_allowed")
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)",
            name=op.f("ck_call_clips_failed_has_code"),
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR clip_key IS NOT NULL", name=op.f("ck_call_clips_ready_has_file")
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 100", name=op.f("ck_call_clips_title_length")
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 500", name=op.f("ck_call_clips_note_length")
        ),
        sa.CheckConstraint(
            "char_length(excerpt) <= 4000", name=op.f("ck_call_clips_excerpt_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recording_id"],
            ["call_recordings.tenant_id", "call_recordings.id"],
            name=op.f("fk_call_clips_tenant_id_recording_id_call_recordings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "made_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_call_clips_tenant_id_made_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_call_clips_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_clips")),
    )
    op.create_index(
        "ix_call_clips_tenant_id_recording_id_created_at",
        "call_clips",
        ["tenant_id", "recording_id", "created_at"],
    )
    op.execute("ALTER TABLE call_clips ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE call_clips FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY call_clips_tenant_isolation ON call_clips
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # The range, the excerpt, the maker and the recording are fixed once the clip exists: a
    # different moment is a different clip.
    op.execute(
        """
        CREATE FUNCTION call_clips_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
             OR NEW.recording_id IS DISTINCT FROM OLD.recording_id
             OR NEW.made_by_user_id IS DISTINCT FROM OLD.made_by_user_id
             OR NEW.start_ms IS DISTINCT FROM OLD.start_ms
             OR NEW.end_ms IS DISTINCT FROM OLD.end_ms
             OR NEW.excerpt IS DISTINCT FROM OLD.excerpt
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'the range, excerpt, maker and recording of a clip cannot change';
          END IF;
          RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER call_clips_guard BEFORE UPDATE ON call_clips
            FOR EACH ROW EXECUTE FUNCTION call_clips_guard();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS call_clips_guard ON call_clips;")
    op.execute("DROP FUNCTION IF EXISTS call_clips_guard();")
    op.execute("DROP POLICY IF EXISTS call_clips_tenant_isolation ON call_clips;")
    op.drop_index("ix_call_clips_tenant_id_recording_id_created_at", table_name="call_clips")
    op.drop_table("call_clips")
    op.drop_constraint(op.f("uq_call_recordings_tenant_id_id"), "call_recordings", type_="unique")
