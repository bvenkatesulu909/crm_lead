"""Sentinel verification stored with every AI proposal (SN2).

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-26

One nullable column (ADR 0017, decision S5): ``agent_actions.verification`` - which groups of
rules were checked and which warnings the approver should see. Codes and short sentences only,
never record text. Proposals made before this step have none (NULL).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_actions",
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_agent_actions_verification_is_object"),
        "agent_actions",
        "verification IS NULL OR jsonb_typeof(verification) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_agent_actions_verification_is_object"), "agent_actions", type_="check"
    )
    op.drop_column("agent_actions", "verification")
