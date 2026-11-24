"""The voice receptionist's tools: callbacks in the approval queue (ADR 0038, VR3).

Revision ID: 0074
Revises: 0073
Create Date: 2026-11-23

* ``agent_actions.agent`` may now be ``receptionist`` (a callback the visitor asked for, proposed
  by the voice receptionist and approved by a person). The list is written out here on purpose: a
  migration must not change when the code does.
* ``public_chat_sessions.callback_requested_at``: a conversation asks for at most one callback.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
BEFORE = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes')"
)
AFTER = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes', 'receptionist')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", AFTER)
    op.add_column(
        "public_chat_sessions", sa.Column("callback_requested_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("public_chat_sessions", "callback_requested_at")
    op.execute("DELETE FROM agent_actions WHERE agent = 'receptionist'")
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", BEFORE)
