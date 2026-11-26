"""The photo enhancer's "use in proposal decks" choice (ADR 0039, PE5).

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-22

One column on ``photo_enhancements``: ``in_decks``. A sales person chooses which adjusted copies may
appear in proposal decks; nothing is put in a customer-facing deck without that choice. Only a
finished copy can be chosen: the database refuses the flag on a waiting or failed request.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "photo_enhancements",
        sa.Column("in_decks", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_photo_enhancements_deck_only_when_ready"),
        "photo_enhancements",
        "NOT in_decks OR status = 'ready'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_photo_enhancements_deck_only_when_ready"), "photo_enhancements", type_="check"
    )
    op.drop_column("photo_enhancements", "in_decks")
