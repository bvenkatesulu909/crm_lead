"""The approval queue learns follow-up drafts (ADR 0036, FM2).

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-21

A follow-up e-mail drafted by the system has the author ``follow_up``. The author list is written
out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
BEFORE = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes', 'receptionist', 'video_brief')"
)
AFTER = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes', 'receptionist', 'video_brief', 'follow_up')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM agent_actions WHERE agent = 'follow_up'")
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", BEFORE)
