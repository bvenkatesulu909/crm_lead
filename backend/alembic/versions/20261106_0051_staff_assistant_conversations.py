"""The staff assistant's short conversation memory (ADR 0023, step VM1).

* ``staff_assistant_conversations``: one conversation of one employee with the staff assistant.
* ``staff_assistant_turns``: the screened question and the cleaned answer of each turn; the last few
  are given to the model again so a follow-up question ("and the second one?") can be answered.
* Forced row-level security with the tenant policy on both (ADR 0009). The owner check (only the
  employee who had the conversation may read it) is in the repository; the worker deletes quiet
  conversations after 24 hours, and their turns go with them (ON DELETE CASCADE).

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONVERSATIONS = "staff_assistant_conversations"
TURNS = "staff_assistant_turns"


def _timestamp(name: str, default: str = "now()") -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text(default), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        CONVERSATIONS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _timestamp("last_turn_at"),
        sa.Column("turn_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "turn_count >= 0",
            name=op.f("ck_staff_assistant_conversations_turn_count_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_staff_assistant_conversations_tenant_id_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_staff_assistant_conversations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_assistant_conversations")),
        sa.UniqueConstraint(
            "tenant_id", "id", name=op.f("uq_staff_assistant_conversations_tenant_id_id")
        ),
    )
    op.create_index(
        "ix_staff_assistant_conversations_last_turn_at", CONVERSATIONS, ["last_turn_at"]
    )
    op.create_index(
        "ix_staff_assistant_conversations_tenant_id_user_id",
        CONVERSATIONS,
        ["tenant_id", "user_id"],
    )
    op.create_table(
        TURNS,
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _timestamp("created_at", "clock_timestamp()"),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_staff_assistant_turns_role_allowed")
        ),
        sa.CheckConstraint(
            "char_length(content) <= 8000", name=op.f("ck_staff_assistant_turns_content_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            [f"{CONVERSATIONS}.tenant_id", f"{CONVERSATIONS}.id"],
            name=op.f(
                "fk_staff_assistant_turns_tenant_id_conversation_id_staff_assistant_conversations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_staff_assistant_turns_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_assistant_turns")),
    )
    op.create_index(
        "ix_staff_assistant_turns_tenant_id_conversation_id_seq",
        TURNS,
        ["tenant_id", "conversation_id", "seq"],
    )
    for table in (CONVERSATIONS, TURNS):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id = crm_current_tenant())
                WITH CHECK (tenant_id = crm_current_tenant());
            """
        )


def downgrade() -> None:
    for table in (TURNS, CONVERSATIONS):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_index("ix_staff_assistant_turns_tenant_id_conversation_id_seq", table_name=TURNS)
    op.drop_table(TURNS)
    op.drop_index("ix_staff_assistant_conversations_tenant_id_user_id", table_name=CONVERSATIONS)
    op.drop_index("ix_staff_assistant_conversations_last_turn_at", table_name=CONVERSATIONS)
    op.drop_table(CONVERSATIONS)
