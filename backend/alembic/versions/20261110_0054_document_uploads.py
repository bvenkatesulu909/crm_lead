"""Direct uploads: pending document uploads (ADR 0025, DU2)

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-10

One new table, ``document_uploads``: an upload a person has started (permission, record, name and
size already checked) whose file goes straight from the browser to the file store under
``pending/{tenant}/{upload}``. ``finish`` turns it into a document after the same checks as a
normal upload. ENABLE + FORCE row-level security and the tenant policy (ADR 0009). Rows are
short-lived: the worker deletes them (and their pending file) a day after they were started.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_uploads",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "customer_visible", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("description", sa.String(length=500), nullable=True),
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
            "record_type IN ('account', 'opportunity')",
            name=op.f("ck_document_uploads_record_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'finished', 'failed', 'expired')",
            name=op.f("ck_document_uploads_status_allowed"),
        ),
        sa.CheckConstraint(
            "declared_size >= 1", name=op.f("ck_document_uploads_declared_size_positive")
        ),
        sa.CheckConstraint(
            "(status = 'finished') = (document_id IS NOT NULL)",
            name=op.f("ck_document_uploads_finished_has_document"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_document_uploads_tenant_id_created_by_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_document_uploads_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_uploads")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_document_uploads_tenant_id_id")),
    )
    op.create_index(
        "ix_document_uploads_tenant_id_user_created",
        "document_uploads",
        ["tenant_id", "created_by_user_id", "created_at"],
    )
    op.execute("ALTER TABLE document_uploads ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE document_uploads FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY document_uploads_tenant_isolation ON document_uploads
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS document_uploads_tenant_isolation ON document_uploads;")
    op.drop_index("ix_document_uploads_tenant_id_user_created", table_name="document_uploads")
    op.drop_table("document_uploads")
