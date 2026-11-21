"""The approval queue learns the call notes agent (ADR 0035, CN4).

Revision ID: 0072
Revises: 0071
Create Date: 2026-11-17

Proposals made from a call-notes draft have the author ``call_notes``. The author list is written
out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
BEFORE = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent')"
)
AFTER = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM agent_actions WHERE agent = 'call_notes'")
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", BEFORE)
