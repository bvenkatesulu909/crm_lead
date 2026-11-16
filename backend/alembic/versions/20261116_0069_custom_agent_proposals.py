"""The approval queue learns custom agents (ADR 0034, AB2a).

Revision ID: 0069
Revises: 0068
Create Date: 2026-11-16

A proposal made by an organisation's own custom agent has the author ``custom_agent`` and names
the agent in the new column ``custom_agent_key`` (registry key ``custom_`` plus 12 letters). The
database keeps the two together: the key is set exactly when the author is ``custom_agent``.

The author list is written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("custom_agent_key", sa.String(length=20)))
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
        "'deck_writer', 'custom_agent')",
    )
    op.create_check_constraint(
        op.f("ck_agent_actions_custom_agent_key_matches_agent"),
        "agent_actions",
        "(agent = 'custom_agent') = (custom_agent_key IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_agent_actions_custom_agent_key_shape"),
        "agent_actions",
        "custom_agent_key IS NULL OR custom_agent_key ~ '^custom_[a-z]{12}$'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agent_actions_custom_agent_key_shape"), "agent_actions", "check")
    op.drop_constraint(
        op.f("ck_agent_actions_custom_agent_key_matches_agent"), "agent_actions", "check"
    )
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
        "'deck_writer')",
    )
    op.drop_column("agent_actions", "custom_agent_key")
