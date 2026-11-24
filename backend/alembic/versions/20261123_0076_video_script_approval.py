"""Approved video scripts remember their proposal; the approval queue learns the video drafter
(ADR 0041, VB5)

Revision ID: 0076
Revises: 0075
Create Date: 2026-11-23

``video_scripts`` gets ``proposal_id`` (the approved proposal an ``ai_draft`` script came from; a
hand-written script has none - a database check keeps the two together). The approval queue learns
one author name, ``video_brief``. The name list is written out on purpose: a migration must not
change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
BEFORE = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes')"
)
AFTER = (
    "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
    "'deck_writer', 'custom_agent', 'call_notes', 'video_brief')"
)


def upgrade() -> None:
    op.add_column("video_scripts", sa.Column("proposal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_video_scripts_tenant_id_proposal_id_agent_actions"),
        "video_scripts",
        "agent_actions",
        ["tenant_id", "proposal_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_video_scripts_proposal_matches_source"),
        "video_scripts",
        "(source = 'ai_draft') = (proposal_id IS NOT NULL)",
    )
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM agent_actions WHERE agent = 'video_brief'")
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(op.f(AGENT_CHECK), "agent_actions", BEFORE)
    op.drop_constraint(op.f("ck_video_scripts_proposal_matches_source"), "video_scripts", "check")
    op.drop_constraint(
        op.f("fk_video_scripts_tenant_id_proposal_id_agent_actions"), "video_scripts", "foreignkey"
    )
    op.drop_column("video_scripts", "proposal_id")
