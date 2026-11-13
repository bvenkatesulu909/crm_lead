"""Call recordings: a recording of a call with a buyer, its cleaned copy and its transcript (ADR 0030, CA1).

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-13

One table, ``call_recordings``: per lead, the language spoken, the buyer's consent (the database
refuses a row without one), a status (``uploading`` -> ``queued`` -> ``processing`` -> ``ready`` or
``failed``/``expired``), the keys of the stored files, and later the transcript with its timed segments.

ENABLE + FORCE row-level security and the one tenant policy (ADR 0009). The application role keeps
UPDATE (the status moves on) but has no DELETE or TRUNCATE privilege: a recording is removed by
deleting its audio (the row and its transcript stay under the lead's own retention). The language and
status lists are written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("uploading", "queued", "processing", "ready", "failed", "expired")
_MAX_BYTES = 524_288_000  # 500 MiB: far above the organisation's limit, a floor against nonsense

_CHECKS = (
    ("language_allowed", "language IN ('hi', 'te', 'en')"),
    ("status_allowed", f"status IN {_STATUSES}"),
    ("declared_size_range", f"declared_size BETWEEN 1 AND {_MAX_BYTES}"),
    ("size_range", f"size_bytes IS NULL OR size_bytes BETWEEN 1 AND {_MAX_BYTES}"),
    ("failed_has_code", "(status = 'failed') = (failure_code IS NOT NULL)"),
    (
        "stored_has_key",
        "status NOT IN ('queued', 'processing', 'ready') OR original_key IS NOT NULL",
    ),
    ("ready_has_transcript", "status <> 'ready' OR transcript_text IS NOT NULL"),
    ("transcript_length", "transcript_text IS NULL OR char_length(transcript_text) <= 500000"),
    (
        "segments_is_list",
        "transcript_segments IS NULL OR jsonb_typeof(transcript_segments) = 'array'",
    ),
    ("duration_range", "duration_seconds IS NULL OR duration_seconds BETWEEN 0 AND 86400"),
)


def upgrade() -> None:
    op.create_table(
        "call_recordings",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_name", sa.String(length=150), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default=sa.text("'uploading'"), nullable=False),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("original_key", sa.Text(), nullable=True),
        sa.Column("clean_key", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("transcript_segments", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("engine", sa.String(length=60), nullable=True),
        sa.Column("audio_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *[
            sa.CheckConstraint(condition, name=op.f(f"ck_call_recordings_{name}"))
            for name, condition in _CHECKS
        ],
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name=op.f("fk_call_recordings_tenant_id_lead_id_leads"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "added_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_call_recordings_tenant_id_added_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_call_recordings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_recordings")),
    )
    op.create_index(
        "ix_call_recordings_tenant_id_lead_id_created_at",
        "call_recordings",
        ["tenant_id", "lead_id", "created_at"],
    )
    op.create_index(
        "ix_call_recordings_tenant_id_status", "call_recordings", ["tenant_id", "status"]
    )

    op.execute("ALTER TABLE call_recordings ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE call_recordings FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY call_recordings_tenant_isolation ON call_recordings
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'call_recordings'
              AND privilege_type IN ('DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE DELETE, TRUNCATE ON call_recordings FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS call_recordings_tenant_isolation ON call_recordings;")
    op.drop_index("ix_call_recordings_tenant_id_status", table_name="call_recordings")
    op.drop_index("ix_call_recordings_tenant_id_lead_id_created_at", table_name="call_recordings")
    op.drop_table("call_recordings")
