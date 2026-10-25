"""Public website chat: visitor conversations and messages, with tenant-isolation RLS (PC3).

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-25

Two tables (ADR 0013): ``public_chat_sessions`` (one per visitor conversation; only the SHA-256
hash of its token and a keyed hash of the visitor's address are stored; the lead it produced)
and ``public_chat_messages``. Both get ENABLE + FORCE row-level security and the tenant policy
(ADR 0009); the guard test fails a tenant table without it. Conversations without a lead are
deleted after 30 days by the worker (step PC4), so DELETE stays allowed.

(Alembic's comparison also proposed changing the rag_* tenant foreign keys on the development
database; that is unrelated and deliberately NOT part of this migration.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("public_chat_sessions", "public_chat_messages")


def _timestamp(name: str, default: str = "now()") -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text(default), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "public_chat_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("visitor_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_public_chat_sessions_token_hash_shape")
        ),
        sa.CheckConstraint(
            "visitor_ip_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_public_chat_sessions_ip_hash_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name=op.f("fk_public_chat_sessions_tenant_id_lead_id_leads"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_public_chat_sessions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_chat_sessions")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_public_chat_sessions_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "token_hash", name=op.f("uq_public_chat_sessions_tenant_id_token_hash")
        ),
    )
    op.create_index(
        "ix_public_chat_sessions_tenant_id_visitor_ip_hash_created_at",
        "public_chat_sessions",
        ["tenant_id", "visitor_ip_hash", "created_at"],
        unique=False,
    )
    op.create_table(
        "public_chat_messages",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _timestamp("created_at", "clock_timestamp()"),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "role IN ('visitor', 'assistant')", name=op.f("ck_public_chat_messages_role_allowed")
        ),
        sa.CheckConstraint(
            "char_length(content) <= 8000", name=op.f("ck_public_chat_messages_content_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["public_chat_sessions.tenant_id", "public_chat_sessions.id"],
            name=op.f("fk_public_chat_messages_tenant_id_session_id_public_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_public_chat_messages_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_chat_messages")),
    )
    op.create_index(
        "ix_public_chat_messages_tenant_id_created_at",
        "public_chat_messages",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_public_chat_messages_tenant_id_session_id_seq",
        "public_chat_messages",
        ["tenant_id", "session_id", "seq"],
        unique=False,
    )

    # Row-level security: the same expression for USING and WITH CHECK; an unset app.tenant_id
    # gives no rows and rejects inserts (fail closed). The table names are fixed identifiers.
    for table in _TABLES:
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
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_index(
        "ix_public_chat_messages_tenant_id_session_id_seq", table_name="public_chat_messages"
    )
    op.drop_index("ix_public_chat_messages_tenant_id_created_at", table_name="public_chat_messages")
    op.drop_table("public_chat_messages")
    op.drop_index(
        "ix_public_chat_sessions_tenant_id_visitor_ip_hash_created_at",
        table_name="public_chat_sessions",
    )
    op.drop_table("public_chat_sessions")
