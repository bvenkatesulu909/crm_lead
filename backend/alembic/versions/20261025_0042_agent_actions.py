"""Approval queue: actions an AI proposed, waiting for a person's decision (AP1).

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-25

One table (ADR 0014): ``agent_actions``. ENABLE + FORCE row-level security and the tenant
policy (ADR 0009); the guard test fails a tenant table without it. Rows are history: DELETE and
TRUNCATE are revoked from the application role, and a check constraint refuses a decision by
the person who asked for the action (no self-approval, also enforced in the service).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_actions"


def _timestamp(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _user_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        ["users.tenant_id", "users.id"],
        name=op.f(f"fk_agent_actions_tenant_id_{column}_users"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("result", sa.String(length=500), nullable=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'failed')",
            name=op.f("ck_agent_actions_status_allowed"),
        ),
        sa.CheckConstraint(
            "target_type IN ('lead', 'account', 'contact')",
            name=op.f("ck_agent_actions_target_type_allowed"),
        ),
        sa.CheckConstraint(
            "agent IN ('staff_assistant')", name=op.f("ck_agent_actions_agent_allowed")
        ),
        sa.CheckConstraint(
            "kind ~ '^[a-z_]+\\.[a-z_]+$'", name=op.f("ck_agent_actions_kind_shape")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_agent_actions_payload_is_object")
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500", name=op.f("ck_agent_actions_reason_length")
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name=op.f("ck_agent_actions_decided_when_final"),
        ),
        sa.CheckConstraint(
            "decided_by_user_id IS NULL OR decided_by_user_id <> requested_by_user_id",
            name=op.f("ck_agent_actions_no_self_decision"),
        ),
        _user_fk("requested_by_user_id"),
        _user_fk("decided_by_user_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_agent_actions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_actions")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_agent_actions_tenant_id_id")),
    )
    op.create_index(
        "ix_agent_actions_tenant_id_status_expires_at",
        _TABLE,
        ["tenant_id", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_actions_tenant_id_requested_by_user_id_status",
        _TABLE,
        ["tenant_id", "requested_by_user_id", "status"],
        unique=False,
    )
    # Row-level security: the same expression for USING and WITH CHECK; an unset app.tenant_id
    # gives no rows and rejects inserts (fail closed). The table name is a fixed identifier.
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {_TABLE}_tenant_isolation ON {_TABLE}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Proposals are history: decisions update them, but nothing may delete them.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'agent_actions'
              AND privilege_type IN ('DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE DELETE, TRUNCATE ON agent_actions FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_tenant_isolation ON {_TABLE};")
    op.drop_index("ix_agent_actions_tenant_id_requested_by_user_id_status", table_name=_TABLE)
    op.drop_index("ix_agent_actions_tenant_id_status_expires_at", table_name=_TABLE)
    op.drop_table(_TABLE)
