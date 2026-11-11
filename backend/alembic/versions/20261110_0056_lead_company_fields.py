"""Leads: the company behind a lead - website, industry, size band (BP-02, ADR 0026 step EN1).

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-10

Three nullable columns on ``leads``. The database itself refuses anything but ``https://<host>``
for the website (lower case, no path, port or user info), an unknown industry key and an unknown
size band - so a value from outside (EN3 suggestions) can never smuggle free text into them.
Existing leads simply have no values. ``leads`` already has forced row-level security
(migration 0029); nothing changes there.

The industry keys and the website pattern are written out here on purpose: a migration must
not change when the application code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WEBSITE_PATTERN = r"^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
_INDUSTRIES = (
    "agriculture", "automotive", "banking_finance", "construction", "consulting", "education",
    "energy", "government", "healthcare", "hospitality", "information_technology", "insurance",
    "legal", "logistics", "manufacturing", "media", "non_profit", "pharmaceuticals",
    "real_estate", "retail", "telecom", "textiles", "travel", "wholesale", "other",
)  # fmt: skip
_SIZES = ("1-10", "11-50", "51-200", "201-1000", "1001+")

_CHECKS = (
    (
        "company_website_shape",
        f"company_website IS NULL OR company_website ~ '{_WEBSITE_PATTERN}'",
    ),
    ("company_industry_allowed", f"company_industry IS NULL OR company_industry IN {_INDUSTRIES}"),
    ("company_size_allowed", f"company_size IS NULL OR company_size IN {_SIZES}"),
)


def upgrade() -> None:
    op.add_column("leads", sa.Column("company_website", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("company_industry", sa.String(length=40), nullable=True))
    op.add_column("leads", sa.Column("company_size", sa.String(length=10), nullable=True))
    for name, condition in _CHECKS:
        op.create_check_constraint(op.f(f"ck_leads_{name}"), "leads", condition)


def downgrade() -> None:
    for name, _condition in reversed(_CHECKS):
        op.drop_constraint(op.f(f"ck_leads_{name}"), "leads", type_="check")
    for column in ("company_size", "company_industry", "company_website"):
        op.drop_column("leads", column)
