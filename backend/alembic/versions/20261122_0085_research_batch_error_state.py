"""A batch can end because of an error (ADR 0042, BR3).

Revision ID: 0085
Revises: 0084
Create Date: 2026-11-22

The worker step stops a batch as ``stopped_error`` when it cannot go on: its starter is no longer an
active member of staff, or its step job died after all its retries. The list is written out here on
purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_research_batches_status_allowed"
BEFORE = "status IN ('running', 'finished', 'cancelled', 'stopped_budget')"
AFTER = "status IN ('running', 'finished', 'cancelled', 'stopped_budget', 'stopped_error')"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "research_batches", type_="check")
    op.create_check_constraint(op.f(CHECK), "research_batches", AFTER)


def downgrade() -> None:
    # The guard trigger refuses to change a finished batch; this one change is the point.
    op.execute("ALTER TABLE research_batches DISABLE TRIGGER research_batches_guard;")
    op.execute(
        "UPDATE research_batches SET status = 'stopped_budget' WHERE status = 'stopped_error'"
    )
    op.execute("ALTER TABLE research_batches ENABLE TRIGGER research_batches_guard;")
    op.drop_constraint(op.f(CHECK), "research_batches", type_="check")
    op.create_check_constraint(op.f(CHECK), "research_batches", BEFORE)
