"""The approval queue learns the deal risk coach (ADR 0037, DR5)

Revision ID: 0087
Revises: 0086
Create Date: 2026-11-27

One author name, ``deal_risk_coach``: its follow-up tasks wait in the approval queue like every
other AI suggestion. The name list is written out on purpose: a migration must not change when the
code does.

Numbered 0087 to follow main's newest migration (0086) after main's chain was renumbered.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
BEFORE = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes', 'receptionist', 'video_brief', 'follow_up')"
)
AFTER = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes', 'receptionist', 'video_brief', 'follow_up', "
    "'deal_risk_coach')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM agent_actions WHERE agent = 'deal_risk_coach'")
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", BEFORE)
