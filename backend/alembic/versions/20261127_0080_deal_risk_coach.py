"""The approval queue learns the deal risk coach (ADR 0037, DR5)

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-27

One author name, ``deal_risk_coach``: its follow-up tasks wait in the approval queue like every
other AI suggestion. The name list is written out on purpose: a migration must not change when the
code does.

0079 is the lead e-mail consent migration once it is renumbered after 0078 (main had two
migrations numbered 0073; see the fix that renumbers it). This migration needs that fix first.
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
    "'deck_writer', 'custom_agent', 'call_notes', 'receptionist', 'video_brief', "
    "'deal_risk_coach')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM agent_actions WHERE agent = 'deal_risk_coach'")
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", BEFORE)
