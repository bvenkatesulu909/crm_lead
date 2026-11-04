"""Allow the lead agent as the author of an approval proposal (ADR 0022)

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_agent_actions_agent_allowed"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier')",
    )
