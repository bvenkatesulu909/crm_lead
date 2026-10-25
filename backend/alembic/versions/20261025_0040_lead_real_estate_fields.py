"""Leads: real-estate wishes - property type, budget in whole rupees, location (PC2, CRM-105).

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-25

Four nullable columns on ``leads`` (ADR 0013): ``property_type`` (apartment | villa | plot |
commercial), ``budget_min_inr`` / ``budget_max_inr`` (BIGINT, whole rupees - no fractions, so no
float anywhere) and ``location``. The database refuses unknown property types, negative budgets
and a minimum above the maximum by itself. Existing leads simply have no values. ``leads``
already has forced row-level security (migration 0029); nothing changes there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = (
    (
        "property_type_allowed",
        "property_type IS NULL OR property_type IN ('apartment', 'villa', 'plot', 'commercial')",
    ),
    (
        "budget_not_negative",
        "(budget_min_inr IS NULL OR budget_min_inr >= 0) "
        "AND (budget_max_inr IS NULL OR budget_max_inr >= 0)",
    ),
    (
        "budget_in_order",
        "budget_min_inr IS NULL OR budget_max_inr IS NULL OR budget_min_inr <= budget_max_inr",
    ),
)


def upgrade() -> None:
    op.add_column("leads", sa.Column("property_type", sa.String(length=20), nullable=True))
    op.add_column("leads", sa.Column("budget_min_inr", sa.BigInteger(), nullable=True))
    op.add_column("leads", sa.Column("budget_max_inr", sa.BigInteger(), nullable=True))
    op.add_column("leads", sa.Column("location", sa.String(length=160), nullable=True))
    for name, condition in _CHECKS:
        op.create_check_constraint(op.f(f"ck_leads_{name}"), "leads", condition)


def downgrade() -> None:
    for name, _condition in reversed(_CHECKS):
        op.drop_constraint(op.f(f"ck_leads_{name}"), "leads", type_="check")
    for column in ("location", "budget_max_inr", "budget_min_inr", "property_type"):
        op.drop_column("leads", column)
