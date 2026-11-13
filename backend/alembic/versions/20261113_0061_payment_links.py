"""Payment links and webhook events for UPI payments (ADR 0031, UP1).

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-13

``payment_links``: one Razorpay link per invoice try; at most ONE open (``created``) link per
invoice (a unique partial index); the application role has no DELETE or TRUNCATE.

``payment_events``: one row per verified webhook delivery. Two locks keep it a record: a trigger
that refuses every change except setting ``outcome`` and ``processed_at`` once (and refuses to
delete a row younger than 365 days), and a column-level grant: the application role may UPDATE
only those two columns.

``payment_link_tenant(link_id)``: a narrow SECURITY DEFINER lookup. The webhook arrives with no
tenant, and row-level security hides every row without one, so this returns ONLY the tenant id for
a Razorpay link id (nothing else) to the application role (same pattern as the login lookup,
ADR 0009).

ENABLE + FORCE row-level security and the one tenant policy on both tables. The value lists are
written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINK_STATUSES = ("created", "paid", "cancelled", "expired")
_MAX_PAISE = 10_00_00_000 * 100


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def _revoke(table: str, privileges: str) -> None:
    # Table and privilege names are constants in this file, never input.
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = '{table}'
              AND privilege_type IN ({", ".join(f"'{p.strip()}'" for p in privileges.split(","))})
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE {privileges} ON {table} FROM %I', grantee_name);
          END LOOP;
        END $$;
        """  # noqa: S608
    )


def upgrade() -> None:
    op.create_table(
        "payment_links",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_link_id", sa.String(length=60), nullable=False),
        sa.Column("reference_id", sa.String(length=40), nullable=False),
        sa.Column("short_url", sa.Text(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'created'"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=60), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"status IN {_LINK_STATUSES}", name=op.f("ck_payment_links_status_allowed")
        ),
        sa.CheckConstraint("currency = 'INR'", name=op.f("ck_payment_links_currency_inr")),
        sa.CheckConstraint(
            f"amount_paise BETWEEN 100 AND {_MAX_PAISE}",
            name=op.f("ck_payment_links_amount_range"),
        ),
        sa.CheckConstraint(
            "(status = 'paid') = (provider_payment_id IS NOT NULL)",
            name=op.f("ck_payment_links_paid_has_payment"),
        ),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)",
            name=op.f("ck_payment_links_paid_has_time"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["invoices.tenant_id", "invoices.id"],
            name=op.f("fk_payment_links_tenant_id_invoice_id_invoices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_payment_links_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_payment_links_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_links")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_payment_links_tenant_id_id")),
        sa.UniqueConstraint("provider_link_id", name=op.f("uq_payment_links_provider_link_id")),
        sa.UniqueConstraint(
            "tenant_id", "reference_id", name=op.f("uq_payment_links_tenant_id_reference_id")
        ),
    )
    op.create_index(
        "ix_payment_links_tenant_id_invoice_id", "payment_links", ["tenant_id", "invoice_id"]
    )
    op.create_index(
        "uq_payment_links_one_open_per_invoice",
        "payment_links",
        ["tenant_id", "invoice_id"],
        unique=True,
        postgresql_where=sa.text("status = 'created'"),
    )
    _rls("payment_links")
    _revoke("payment_links", "DELETE, TRUNCATE")

    op.create_table(
        "payment_events",
        sa.Column("payment_link_id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("facts", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('applied', 'already_applied', 'amount_mismatch', 'currency_mismatch', "
            "'invoice_closed', 'ignored')",
            name=op.f("ck_payment_events_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "(outcome IS NULL) = (processed_at IS NULL)",
            name=op.f("ck_payment_events_processed_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(facts) = 'object'", name=op.f("ck_payment_events_facts_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_link_id"],
            ["payment_links.tenant_id", "payment_links.id"],
            name=op.f("fk_payment_events_tenant_id_payment_link_id_payment_links"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_payment_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_events")),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_event_id",
            name=op.f("uq_payment_events_tenant_id_provider_event_id"),
        ),
    )
    op.create_index(
        "ix_payment_events_tenant_id_payment_link_id",
        "payment_events",
        ["tenant_id", "payment_link_id"],
    )
    op.create_index(
        "ix_payment_events_tenant_id_unprocessed", "payment_events", ["tenant_id", "created_at"]
    )
    _rls("payment_events")
    # Lock 1: the trigger binds every role, including the table's owner.
    op.execute(
        """
        CREATE FUNCTION payment_events_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF OLD.outcome IS NOT NULL THEN
              RAISE EXCEPTION 'payment_events outcome is already set';
            END IF;
            IF (to_jsonb(NEW) - 'outcome' - 'processed_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'outcome' - 'processed_at') THEN
              RAISE EXCEPTION 'payment_events rows cannot be changed';
            END IF;
            RETURN NEW;
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'payment_events rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER payment_events_guard BEFORE UPDATE OR DELETE ON payment_events
            FOR EACH ROW EXECUTE FUNCTION payment_events_guard();
        """
    )
    # Lock 2: no table-wide UPDATE or TRUNCATE; only the two bookkeeping columns can be updated.
    _revoke("payment_events", "UPDATE, TRUNCATE")
    op.execute("GRANT UPDATE (outcome, processed_at) ON payment_events TO crm_app;")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION payment_link_tenant(p_link_id text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT l.tenant_id FROM public.payment_links AS l
            WHERE l.provider_link_id = p_link_id
        $$;
        """
    )
    op.execute("ALTER FUNCTION payment_link_tenant(text) OWNER TO crm_owner;")
    op.execute("REVOKE ALL ON FUNCTION payment_link_tenant(text) FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION payment_link_tenant(text) TO crm_app;")
    op.execute(
        """
        COMMENT ON FUNCTION payment_link_tenant(text) IS
        'Webhook lookup before app.tenant_id exists: returns only the tenant id for a Razorpay '
        'link id. SECURITY DEFINER is required because row-level security hides every row '
        'without a tenant.';
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS payment_link_tenant(text);")
    op.execute("DROP TRIGGER IF EXISTS payment_events_guard ON payment_events;")
    op.execute("DROP FUNCTION IF EXISTS payment_events_guard();")
    op.execute("DROP POLICY IF EXISTS payment_events_tenant_isolation ON payment_events;")
    op.drop_index("ix_payment_events_tenant_id_unprocessed", table_name="payment_events")
    op.drop_index("ix_payment_events_tenant_id_payment_link_id", table_name="payment_events")
    op.drop_table("payment_events")
    op.execute("DROP POLICY IF EXISTS payment_links_tenant_isolation ON payment_links;")
    op.drop_index("uq_payment_links_one_open_per_invoice", table_name="payment_links")
    op.drop_index("ix_payment_links_tenant_id_invoice_id", table_name="payment_links")
    op.drop_table("payment_links")
