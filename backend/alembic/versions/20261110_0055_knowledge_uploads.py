"""Direct uploads for knowledge documents (ADR 0025, DU3b)

Revision ID: 0055
Revises: 0054
Create Date: 2026-11-10

The knowledge module's own pending-upload table (modules never write each other's tables, so it
does not share ``document_uploads``): a knowledge upload a manager has started (permission,
visibility, account, document to replace, name and size checked) whose file goes straight from the
browser to the file store under ``pending/{tenant}/{upload}``. ``finish`` indexes it like a normal
upload. ENABLE + FORCE row-level security and the tenant policy (ADR 0009); deleted by the worker
a day after it was started.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_uploads",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("replaces_document_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('internal', 'customer_visible')",
            name=op.f("ck_kb_uploads_visibility_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'finished', 'failed', 'expired')",
            name=op.f("ck_kb_uploads_status_allowed"),
        ),
        sa.CheckConstraint("declared_size >= 1", name=op.f("ck_kb_uploads_declared_size_positive")),
        sa.CheckConstraint(
            "(status = 'finished') = (document_id IS NOT NULL)",
            name=op.f("ck_kb_uploads_finished_has_document"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_kb_uploads_tenant_id_created_by_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kb_uploads_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_uploads")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_kb_uploads_tenant_id_id")),
    )
    op.create_index(
        "ix_kb_uploads_tenant_id_user_created",
        "kb_uploads",
        ["tenant_id", "created_by_user_id", "created_at"],
    )
    op.execute("ALTER TABLE kb_uploads ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kb_uploads FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY kb_uploads_tenant_isolation ON kb_uploads
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_uploads_tenant_isolation ON kb_uploads;")
    op.drop_index("ix_kb_uploads_tenant_id_user_created", table_name="kb_uploads")
    op.drop_table("kb_uploads")
