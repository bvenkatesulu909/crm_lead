"""Proposals from an outside AI client (MCP5a, ADR 0020).

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-31

``agent_actions.agent`` may now also be ``mcp_client`` and a new nullable column
``via_client`` keeps the verified application the proposal came through (e.g. ``crm-mcp``).
Existing rows are staff-assistant proposals and keep ``via_client`` NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_agent_actions_agent_allowed"


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("via_client", sa.String(length=64), nullable=True))
    op.drop_constraint(op.f(CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(CHECK), "agent_actions", "agent IN ('staff_assistant', 'mcp_client')"
    )
    # A proposal made through a client names it; one made by our own assistant has none.
    op.create_check_constraint(
        op.f("ck_agent_actions_via_client_matches_agent"),
        "agent_actions",
        "(agent = 'mcp_client') = (via_client IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agent_actions_via_client_matches_agent"), "agent_actions", "check")
    op.drop_constraint(op.f(CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(CHECK), "agent_actions", "agent IN ('staff_assistant')")
    op.drop_column("agent_actions", "via_client")
