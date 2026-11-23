"""Projects and units for reservations (ADR 0040, RP1).

Revision ID: 0073
Revises: 0072
Create Date: 2026-11-22

Two tables: ``property_projects`` and ``property_units``. ENABLE + FORCE row-level security and
the tenant policy on both (ADR 0009). A unit belongs to a project of the same tenant (composite
key), its code is unique inside the project ignoring capitals, and the database refuses anything
outside the unit types and statuses written here (a migration must not change when the code does).
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _common() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "property_projects",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("rera_number", sa.String(length=40), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_common(),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200", name=op.f("ck_property_projects_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_property_projects_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_projects")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_property_projects_tenant_id_id")),
    )
    op.create_index(
        "uq_property_projects_tenant_id_lower_name",
        "property_projects",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )
    _tenant_policy("property_projects")

    op.create_table(
        "property_units",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("unit_code", sa.String(length=40), nullable=False),
        sa.Column("unit_type", sa.String(length=20), nullable=False),
        sa.Column("area_sqft", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'available'"), nullable=False
        ),
        *_common(),
        sa.CheckConstraint(
            "unit_type IN ('apartment', 'villa', 'plot', 'commercial')",
            name=op.f("ck_property_units_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('available', 'blocked', 'reserved', 'sold')",
            name=op.f("ck_property_units_status_allowed"),
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_property_units_price_not_negative")),
        sa.CheckConstraint(
            "area_sqft IS NULL OR area_sqft > 0", name=op.f("ck_property_units_area_positive")
        ),
        sa.CheckConstraint(
            "char_length(unit_code) BETWEEN 1 AND 40", name=op.f("ck_property_units_code_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["property_projects.tenant_id", "property_projects.id"],
            name=op.f("fk_property_units_tenant_id_project_id_property_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_property_units_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_units")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_property_units_tenant_id_id")),
    )
    op.create_index(
        "uq_property_units_project_lower_code",
        "property_units",
        ["tenant_id", "project_id", sa.text("lower(unit_code)")],
        unique=True,
    )
    op.create_index("ix_property_units_tenant_id_status", "property_units", ["tenant_id", "status"])
    _tenant_policy("property_units")


def downgrade() -> None:
    op.drop_table("property_units")
    op.drop_table("property_projects")
