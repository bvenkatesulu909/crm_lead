"""Leads: the language the advisor should call in (ADR 0027, step VL1).

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-12

One nullable column on ``leads``. The database itself refuses anything but ``en``, ``hi`` or
``te``, so a value from outside (the website chat's language switch) can never smuggle free text
into it. Existing leads simply have no value. ``leads`` already has forced row-level security
(migration 0029); nothing changes there. The three codes are written out here on purpose: a
migration must not change when the application code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "preferred_language_allowed"


def upgrade() -> None:
    op.add_column("leads", sa.Column("preferred_language", sa.String(length=2), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_leads_{_CHECK}"),
        "leads",
        "preferred_language IS NULL OR preferred_language IN ('en', 'hi', 'te')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(f"ck_leads_{_CHECK}"), "leads", type_="check")
    op.drop_column("leads", "preferred_language")
