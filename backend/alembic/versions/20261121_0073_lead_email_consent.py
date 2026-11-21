"""E-mail consent on leads (ADR 0036, FM1).

Revision ID: 0073
Revises: 0072
Create Date: 2026-11-21

Contacts already had a consent answer; leads, the people most likely to get automatic follow-ups,
had none, so nothing could stop a message to a lead who said no. Every existing lead starts as
"unknown" (nothing is ever set to "granted" without an explicit statement). The database keeps the
date and the answer together: a date exists exactly when the answer is not "unknown".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("email_consent", sa.String(length=20), server_default="unknown", nullable=False),
    )
    op.add_column("leads", sa.Column("email_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_leads_email_consent_allowed"),
        "leads",
        "email_consent IN ('unknown', 'granted', 'withdrawn')",
    )
    op.create_check_constraint(
        op.f("ck_leads_consent_dated"),
        "leads",
        "(email_consent = 'unknown') = (email_consent_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_leads_consent_dated"), "leads", type_="check")
    op.drop_constraint(op.f("ck_leads_email_consent_allowed"), "leads", type_="check")
    op.drop_column("leads", "email_consent_at")
    op.drop_column("leads", "email_consent")
