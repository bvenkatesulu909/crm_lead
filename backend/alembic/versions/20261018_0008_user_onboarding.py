"""User onboarding (ADR 0004): organisation sign-up codes, access requests, code attempts.

- tenants.signup_code: random code an organisation's admins give to people who sign up
  themselves; filled by crm_new_signup_code() (strong randomness from gen_random_uuid()).
- access_requests: people who signed up in Keycloak and wait for an admin's decision.
- signup_code_attempts: wrong codes, for the 5-per-hour limit.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I, L, O, 0, 1 (easy to misread)
PATTERN = "^[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}$"


def upgrade() -> None:
    # 12 characters from 12 random bytes of a v4 UUID (bytes 6 and 8 carry version/variant
    # bits, so they are skipped). Format: XXXX-XXXX-XXXX.
    op.execute(
        f"""
        CREATE FUNCTION crm_new_signup_code() RETURNS text
        LANGUAGE sql VOLATILE AS $$
          SELECT substr(c, 1, 4) || '-' || substr(c, 5, 4) || '-' || substr(c, 9, 4)
          FROM (
            SELECT string_agg(
                     substr('{ALPHABET}', (get_byte(b, p) % {len(ALPHABET)}) + 1, 1), ''
                     ORDER BY p) AS c
            FROM (SELECT decode(replace(gen_random_uuid()::text, '-', ''), 'hex') AS b) AS r,
                 unnest(ARRAY[0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14]) AS p
          ) AS s
        $$;
        """  # noqa: S608 - ALPHABET is a constant in this file, not user input
    )
    op.add_column(
        "tenants",
        sa.Column(
            "signup_code",
            sa.String(14),
            server_default=sa.text("crm_new_signup_code()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_tenants_signup_code", "tenants", ["signup_code"])
    op.create_check_constraint(
        op.f("ck_tenants_signup_code_format"), "tenants", f"signup_code ~ '{PATTERN}'"
    )

    op.create_table(
        "access_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idp_issuer", sa.String(255), nullable=False),
        sa.Column("idp_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_role", sa.String(30), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_requests"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_access_requests_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_access_requests_tenant_id_decided_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_access_requests_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name=op.f("ck_access_requests_decision_consistent"),
        ),
    )
    op.create_index(
        "uq_access_requests_identity_pending",
        "access_requests",
        ["idp_issuer", "idp_subject"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_access_requests_tenant_id_status", "access_requests", ["tenant_id", "status"]
    )

    op.create_table(
        "signup_code_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("idp_issuer", sa.String(255), nullable=False),
        sa.Column("idp_subject", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signup_code_attempts"),
    )
    op.create_index(
        "ix_signup_code_attempts_identity_created_at",
        "signup_code_attempts",
        ["idp_issuer", "idp_subject", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("signup_code_attempts")
    op.drop_table("access_requests")
    op.drop_constraint(op.f("ck_tenants_signup_code_format"), "tenants", type_="check")
    op.drop_constraint("uq_tenants_signup_code", "tenants", type_="unique")
    op.drop_column("tenants", "signup_code")
    op.execute("DROP FUNCTION crm_new_signup_code()")
