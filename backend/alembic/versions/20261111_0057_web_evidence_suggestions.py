"""Web evidence: the company details suggested from a company's own website (BP-02, ADR 0026 EN3).

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-11

One nullable JSON column on ``web_evidence``: for a lookup of a company's own website (source
``company_site``) it holds the suggested ``website``, ``industry`` and ``size`` and the pages read.
The row stays insert-only (migration 0045's trigger and grants are untouched); a person's choice
is saved on the lead, never by changing the evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "web_evidence",
        sa.Column("suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_web_evidence_suggestions_is_object"),
        "web_evidence",
        "suggestions IS NULL OR jsonb_typeof(suggestions) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_web_evidence_suggestions_is_object"), "web_evidence", type_="check")
    op.drop_column("web_evidence", "suggestions")
