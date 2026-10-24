"""Communication Center: e-mail templates and message history, with tenant-isolation RLS (CC1).

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-24

Two tables (ADR 0012): ``email_templates`` and ``email_messages``. Each gets ENABLE + FORCE
row-level security and one tenant policy (ADR 0009), like every tenant table; the guard test
fails a tenant table without it. Messages are history: the application may insert them and
move their status forward, but never delete them.

Only the communication tables are created here. (Alembic's automatic comparison also proposed
changing the tenant foreign keys of ``rag_feedback`` and ``rag_queries`` on the development
database; that is unrelated and deliberately NOT part of this migration.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("email_templates", "email_messages")
_MESSAGE_INDEXES = (
    ("ix_email_messages_tenant_id_account_id", ["tenant_id", "account_id"]),
    ("ix_email_messages_tenant_id_contact_id", ["tenant_id", "contact_id"]),
    ("ix_email_messages_tenant_id_created_at", ["tenant_id", "created_at"]),
    ("ix_email_messages_tenant_id_lead_id", ["tenant_id", "lead_id"]),
    ("ix_email_messages_tenant_id_opportunity_id", ["tenant_id", "opportunity_id"]),
    (
        "ix_email_messages_tenant_id_sent_by_user_id_created_at",
        ["tenant_id", "sent_by_user_id", "created_at"],
    ),
)


def _tenant_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        name=op.f(f"fk_{table}_tenant_id_{column}_{target}"),
        ondelete="RESTRICT",
    )


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("btrim(body) <> ''", name=op.f("ck_email_templates_body_not_blank")),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_email_templates_name_not_blank")),
        sa.CheckConstraint(
            "btrim(subject) <> ''", name=op.f("ck_email_templates_subject_not_blank")
        ),
        sa.CheckConstraint(
            "char_length(body) <= 20000", name=op.f("ck_email_templates_body_length")
        ),
        _tenant_fk("email_templates", "created_by_user_id", "users"),
        _tenant_fk("email_templates", "updated_by_user_id", "users"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_email_templates_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_templates")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_email_templates_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_email_templates_tenant_id_name")),
    )
    op.create_table(
        "email_messages",
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("sent_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "(direction = 'inbound_logged') = (status = 'logged')",
            name=op.f("ck_email_messages_logged_means_inbound"),
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name=op.f("ck_email_messages_sent_has_time"),
        ),
        sa.CheckConstraint("btrim(body) <> ''", name=op.f("ck_email_messages_body_not_blank")),
        sa.CheckConstraint(
            "btrim(subject) <> ''", name=op.f("ck_email_messages_subject_not_blank")
        ),
        sa.CheckConstraint(
            "direction IN ('outbound', 'inbound_logged')",
            name=op.f("ck_email_messages_direction_allowed"),
        ),
        sa.CheckConstraint(
            "status = 'failed' OR error_code IS NULL",
            name=op.f("ck_email_messages_error_only_if_failed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'logged')",
            name=op.f("ck_email_messages_status_allowed"),
        ),
        sa.CheckConstraint(
            "to_address ~ '^[^@\\s]+@[^@\\s]+$'", name=op.f("ck_email_messages_address_shape")
        ),
        sa.CheckConstraint(
            "(lead_id IS NULL) <> (contact_id IS NULL)",
            name=op.f("ck_email_messages_one_recipient"),
        ),
        sa.CheckConstraint(
            "account_id IS NULL OR opportunity_id IS NULL",
            name=op.f("ck_email_messages_one_related_record"),
        ),
        sa.CheckConstraint(
            "char_length(body) <= 50000", name=op.f("ck_email_messages_body_length")
        ),
        sa.CheckConstraint(
            "lead_id IS NULL OR (account_id IS NULL AND opportunity_id IS NULL)",
            name=op.f("ck_email_messages_lead_has_no_related_record"),
        ),
        _tenant_fk("email_messages", "account_id", "accounts"),
        _tenant_fk("email_messages", "contact_id", "contacts"),
        _tenant_fk("email_messages", "lead_id", "leads"),
        _tenant_fk("email_messages", "opportunity_id", "opportunities"),
        _tenant_fk("email_messages", "sent_by_user_id", "users"),
        _tenant_fk("email_messages", "template_id", "email_templates"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_email_messages_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_messages")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_email_messages_tenant_id_id")),
    )
    for name, columns in _MESSAGE_INDEXES:
        op.create_index(name, "email_messages", columns, unique=False)

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
    # Messages are history: the worker updates their status, but nothing may delete them.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'email_messages'
              AND privilege_type IN ('DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE DELETE, TRUNCATE ON email_messages FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    for name, _columns in reversed(_MESSAGE_INDEXES):
        op.drop_index(name, table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_table("email_templates")
