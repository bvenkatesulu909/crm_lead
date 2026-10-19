"""Identity mapping rules and customer-portal access grants.

1. users: one CRM user per Keycloak identity across ALL tenants (was: per tenant), so a
   verified token determines exactly one tenant.
2. users: unique (tenant_id, id, user_type), the target of the grants foreign key below.
3. portal_access_grants: which customer user may see which customer account. Composite
   foreign keys guarantee: same tenant, and the user really is a customer.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_users_tenant_id_idp_issuer_idp_subject", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_idp_issuer_idp_subject", "users", ["idp_issuer", "idp_subject"]
    )
    op.create_unique_constraint(
        "uq_users_tenant_id_id_user_type", "users", ["tenant_id", "id", "user_type"]
    )

    op.create_table(
        "portal_access_grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("user_type", sa.String(20), server_default=sa.text("'customer'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_portal_access_grants"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_portal_access_grants_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id", "user_type"],
            ["users.tenant_id", "users.id", "users.user_type"],
            name="fk_portal_access_grants_tenant_id_user_id_user_type_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_portal_access_grants_tenant_id_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "account_id",
            name="uq_portal_access_grants_tenant_id_user_id_account_id",
        ),
        sa.CheckConstraint(
            "user_type = 'customer'", name=op.f("ck_portal_access_grants_customer_only")
        ),
    )
    op.create_index(
        "ix_portal_access_grants_tenant_id_account_id",
        "portal_access_grants",
        ["tenant_id", "account_id"],
    )


def downgrade() -> None:
    op.drop_table("portal_access_grants")
    op.drop_constraint("uq_users_tenant_id_id_user_type", "users", type_="unique")
    op.drop_constraint("uq_users_idp_issuer_idp_subject", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_tenant_id_idp_issuer_idp_subject",
        "users",
        ["tenant_id", "idp_issuer", "idp_subject"],
    )
