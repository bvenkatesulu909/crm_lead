"""Organisation branding: colour, texts and a small clean logo (ADR 0032, PD1).

Revision ID: 0063
Revises: 0062
Create Date: 2026-11-13

One row per organisation (or none: the defaults apply). The database repeats the rules the code
applies: a six-digit lower-case hex colour, the text lengths, a logo that is either wholly there
(picture and both sizes) or wholly absent, at most 500 KB and 800 pixels on a side.

ENABLE + FORCE row-level security and the one tenant policy (ADR 0009). The application role keeps
UPDATE (a settings row is changed in place) but has no DELETE or TRUNCATE privilege.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = (
    ("color_format", "primary_color ~ '^[0-9a-f]{6}$'"),
    ("about_length", "char_length(about_text) <= 1500"),
    ("terms_length", "char_length(terms_text) <= 1500"),
    ("contact_length", "char_length(contact_line) <= 200"),
    ("footer_length", "char_length(footer_line) <= 200"),
    (
        "logo_consistent",
        "(logo_png IS NULL) = (logo_width IS NULL) AND (logo_png IS NULL) = (logo_height IS NULL)",
    ),
    ("logo_size", "logo_png IS NULL OR octet_length(logo_png) <= 500000"),
    (
        "logo_dimensions",
        "logo_width IS NULL OR (logo_width BETWEEN 1 AND 800 AND logo_height BETWEEN 1 AND 800)",
    ),
)


def upgrade() -> None:
    op.create_table(
        "organisation_branding",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "primary_color", sa.String(length=6), server_default=sa.text("'1f3a5f'"), nullable=False
        ),
        sa.Column("about_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("terms_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "contact_line", sa.String(length=200), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "footer_line", sa.String(length=200), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("logo_png", sa.LargeBinary(), nullable=True),
        sa.Column("logo_width", sa.Integer(), nullable=True),
        sa.Column("logo_height", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *[
            sa.CheckConstraint(condition, name=op.f(f"ck_organisation_branding_{name}"))
            for name, condition in _CHECKS
        ],
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_organisation_branding_tenant_id_updated_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_organisation_branding_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_organisation_branding")),
    )
    op.execute("ALTER TABLE organisation_branding ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE organisation_branding FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY organisation_branding_tenant_isolation ON organisation_branding
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
            WHERE table_schema = current_schema() AND table_name = 'organisation_branding'
              AND privilege_type IN ('DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format(
              'REVOKE DELETE, TRUNCATE ON organisation_branding FROM %I', grantee_name
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS organisation_branding_tenant_isolation ON organisation_branding;"
    )
    op.drop_table("organisation_branding")
