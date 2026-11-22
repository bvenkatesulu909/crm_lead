"""Property photo enhancer: adjusted copies of photos (ADR 0039, PE2).

Revision ID: 0073
Revises: 0072
Create Date: 2026-11-21

Two changes:

* ``documents`` may hold an *adjusted copy* of a photo (``purpose = 'property_photo_enhanced'``). A
  copy names its original in ``derived_from_id`` (and only a copy does: a check keeps the two
  together); deleting the original deletes its copies, in the database, so nothing is left behind.
* ``photo_enhancements``: one row per request - which photo, who asked, which adjustments (exactly
  what the person asked for, kept as the record of what was done), the state (queued, ready,
  failed) and, once ready, the copy. ENABLE + FORCE row-level security and the tenant policy
  (ADR 0009). The worker updates the row when the copy is made; nothing else changes it.

The purpose list is written out here on purpose: a migration must not change when the code does.
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
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment', 'quote_deck', 'quote_deck_pptx', "
        "'property_photo_enhanced')",
    )
    op.add_column("documents", sa.Column("derived_from_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_tenant_id_derived_from_id_documents"),
        "documents",
        "documents",
        ["tenant_id", "derived_from_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_documents_derived_has_original"),
        "documents",
        "(purpose = 'property_photo_enhanced') = (derived_from_id IS NOT NULL)",
    )
    op.create_index(
        "ix_documents_tenant_id_derived_from_id", "documents", ["tenant_id", "derived_from_id"]
    )

    op.create_table(
        "photo_enhancements",
        sa.Column("original_document_id", sa.Uuid(), nullable=False),
        sa.Column("derived_document_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("failure_code", sa.String(length=30), nullable=True),
        sa.Column("operations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("applied", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_version", sa.String(length=20), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'ready', 'failed')",
            name=op.f("ck_photo_enhancements_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)",
            name=op.f("ck_photo_enhancements_failed_has_code"),
        ),
        sa.CheckConstraint(
            "(status = 'ready') = (derived_document_id IS NOT NULL)",
            name=op.f("ck_photo_enhancements_ready_has_copy"),
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (width IS NOT NULL AND height IS NOT NULL "
            "AND size_bytes IS NOT NULL AND applied IS NOT NULL)",
            name=op.f("ck_photo_enhancements_ready_has_facts"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(operations) = 'object'",
            name=op.f("ck_photo_enhancements_operations_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "original_document_id"],
            ["documents.tenant_id", "documents.id"],
            name=op.f("fk_photo_enhancements_tenant_id_original_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "derived_document_id"],
            ["documents.tenant_id", "documents.id"],
            name=op.f("fk_photo_enhancements_tenant_id_derived_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_photo_enhancements_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_photo_enhancements_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_photo_enhancements")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_photo_enhancements_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "derived_document_id",
            name=op.f("uq_photo_enhancements_tenant_id_derived_document_id"),
        ),
    )
    op.create_index(
        "ix_photo_enhancements_tenant_id_original_document_id",
        "photo_enhancements",
        ["tenant_id", "original_document_id"],
    )
    op.create_index(
        "ix_photo_enhancements_tenant_id_requested_by_user_id_created_at",
        "photo_enhancements",
        ["tenant_id", "requested_by_user_id", "created_at"],
    )
    op.execute("ALTER TABLE photo_enhancements ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE photo_enhancements FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY photo_enhancements_tenant_isolation ON photo_enhancements
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.drop_table("photo_enhancements")
    op.execute("DELETE FROM documents WHERE purpose = 'property_photo_enhanced'")
    op.drop_index("ix_documents_tenant_id_derived_from_id", table_name="documents")
    op.drop_constraint(op.f("ck_documents_derived_has_original"), "documents", type_="check")
    op.drop_constraint(
        op.f("fk_documents_tenant_id_derived_from_id_documents"), "documents", type_="foreignkey"
    )
    op.drop_column("documents", "derived_from_id")
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment', 'quote_deck', 'quote_deck_pptx')",
    )
