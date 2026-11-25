"""The voice receptionist: channel, consent and minutes of a website conversation (ADR 0038).

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-21

* ``public_chat_sessions`` gets ``channel`` (text or web_voice), the consent record of a voice
  conversation (when, and which version of the notice the visitor read) and two per-call
  counters (seconds of speech, turns) that the per-call limits read.
* ``public_chat_daily_stats`` gets ``voice_seconds``: an anonymous count of the speech seconds an
  organisation used that day, kept after the conversations themselves are cleaned up, so the
  organisation's daily and monthly minutes caps can be checked. The counters still only grow.

The check list is written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSIONS = "public_chat_sessions"
STATS = "public_chat_daily_stats"


def upgrade() -> None:
    op.add_column(
        SESSIONS,
        sa.Column("channel", sa.String(20), server_default=sa.text("'text'"), nullable=False),
    )
    op.add_column(SESSIONS, sa.Column("voice_consent_at", sa.DateTime(timezone=True)))
    op.add_column(SESSIONS, sa.Column("voice_consent_version", sa.Integer()))
    op.add_column(
        SESSIONS, sa.Column("voice_seconds", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        SESSIONS, sa.Column("voice_turns", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_public_chat_sessions_channel_allowed"),
        SESSIONS,
        "channel IN ('text', 'web_voice')",
    )
    # A voice conversation always carries the proof that the visitor pressed Start.
    op.create_check_constraint(
        op.f("ck_public_chat_sessions_voice_needs_consent"),
        SESSIONS,
        "channel = 'text' OR (voice_consent_at IS NOT NULL AND voice_consent_version IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_public_chat_sessions_voice_counts_not_negative"),
        SESSIONS,
        "voice_seconds >= 0 AND voice_turns >= 0",
    )

    op.add_column(
        STATS, sa.Column("voice_seconds", sa.BigInteger(), server_default="0", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_public_chat_daily_stats_voice_not_negative"), STATS, "voice_seconds >= 0"
    )
    # The "only grow" lock now covers the new counter too.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {STATS}_only_grow() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.conversations_started < OLD.conversations_started
             OR NEW.leads_saved < OLD.leads_saved
             OR NEW.voice_seconds < OLD.voice_seconds THEN
            RAISE EXCEPTION '{STATS} counters can only grow';
          END IF;
          RETURN NEW;
        END
        $$;
        """  # noqa: S608 - STATS is a constant of this file, not input
    )


def downgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {STATS}_only_grow() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.conversations_started < OLD.conversations_started
             OR NEW.leads_saved < OLD.leads_saved THEN
            RAISE EXCEPTION '{STATS} counters can only grow';
          END IF;
          RETURN NEW;
        END
        $$;
        """  # noqa: S608
    )
    op.drop_constraint(op.f("ck_public_chat_daily_stats_voice_not_negative"), STATS)
    op.drop_column(STATS, "voice_seconds")
    for name in ("voice_counts_not_negative", "voice_needs_consent", "channel_allowed"):
        op.drop_constraint(op.f(f"ck_public_chat_sessions_{name}"), SESSIONS)
    for column in (
        "voice_turns",
        "voice_seconds",
        "voice_consent_version",
        "voice_consent_at",
        "channel",
    ):
        op.drop_column(SESSIONS, column)
