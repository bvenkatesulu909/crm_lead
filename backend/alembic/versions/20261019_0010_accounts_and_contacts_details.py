"""Accounts and contacts details (Phase B).

accounts: segment (customer segmentation) and preferred contact channel.
contacts: mobile, department, primary flag (at most one primary per account), preferred
channel, e-mail consent with the date it was given/withdrawn, and do-not-call.

Only new nullable columns or columns with defaults: existing rows stay valid.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEGMENTS = "('enterprise', 'mid_market', 'small_business', 'public_sector', 'non_profit')"
CHANNELS = "('email', 'phone', 'mobile', 'post', 'none')"
CONSENTS = "('unknown', 'granted', 'withdrawn')"


def upgrade() -> None:
    op.add_column("accounts", sa.Column("segment", sa.String(length=30), nullable=True))
    op.add_column("accounts", sa.Column("preferred_channel", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_accounts_segment_allowed"), "accounts", f"segment IS NULL OR segment IN {SEGMENTS}"
    )
    op.create_check_constraint(
        op.f("ck_accounts_preferred_channel_allowed"),
        "accounts",
        f"preferred_channel IS NULL OR preferred_channel IN {CHANNELS}",
    )

    op.add_column("contacts", sa.Column("mobile", sa.String(length=50), nullable=True))
    op.add_column("contacts", sa.Column("department", sa.String(length=100), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("contacts", sa.Column("preferred_channel", sa.String(length=20), nullable=True))
    op.add_column(
        "contacts",
        sa.Column(
            "email_consent",
            sa.String(length=20),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
    )
    op.add_column(
        "contacts", sa.Column("email_consent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "contacts",
        sa.Column("do_not_call", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "uq_contacts_one_primary_per_account",
        "contacts",
        ["tenant_id", "account_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND deleted_at IS NULL"),
    )
    op.create_check_constraint(
        op.f("ck_contacts_primary_needs_account"),
        "contacts",
        "NOT is_primary OR account_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_contacts_preferred_channel_allowed"),
        "contacts",
        f"preferred_channel IS NULL OR preferred_channel IN {CHANNELS}",
    )
    op.create_check_constraint(
        op.f("ck_contacts_email_consent_allowed"), "contacts", f"email_consent IN {CONSENTS}"
    )
    op.create_check_constraint(
        op.f("ck_contacts_consent_dated"),
        "contacts",
        "(email_consent = 'unknown') = (email_consent_at IS NULL)",
    )


def downgrade() -> None:
    for name in (
        "ck_contacts_consent_dated",
        "ck_contacts_email_consent_allowed",
        "ck_contacts_preferred_channel_allowed",
        "ck_contacts_primary_needs_account",
    ):
        op.drop_constraint(op.f(name), "contacts", type_="check")
    op.drop_index("uq_contacts_one_primary_per_account", table_name="contacts")
    for column in (
        "do_not_call",
        "email_consent_at",
        "email_consent",
        "preferred_channel",
        "is_primary",
        "department",
        "mobile",
    ):
        op.drop_column("contacts", column)
    op.drop_constraint(op.f("ck_accounts_preferred_channel_allowed"), "accounts", type_="check")
    op.drop_constraint(op.f("ck_accounts_segment_allowed"), "accounts", type_="check")
    op.drop_column("accounts", "preferred_channel")
    op.drop_column("accounts", "segment")
