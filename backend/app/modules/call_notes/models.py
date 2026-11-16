"""Call notes (ADR 0035, CN1): a drafted note per recording and one row per checklist line.

``call_notes`` is one run (which frame, which version, how many claims the code turned into
unknown); ``call_note_lines`` are its lines. Both are insert-only - the database refuses an UPDATE
and an early DELETE - so a draft can always be shown exactly as it was. A line is in one of three
states and the database holds the shape of each: *stated* has a value, a quote and its time;
*assumed* also has a reason; *unknown* has nothing but, at most, a code saying why. The
organisation's choice of frame lives in ``call_note_settings`` (one row each, editable with a
version check).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)
from app.modules.call_notes import rules


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CallNote(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "call_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "recording_id", "version_no"),
        ForeignKeyConstraint(
            ["tenant_id", "recording_id"],
            ["call_recordings.tenant_id", "call_recordings.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("framework", rules.FRAMEWORK_NAMES), name="framework_allowed"),
        CheckConstraint("version_no >= 1", name="version_positive"),
        CheckConstraint("char_length(model_name) BETWEEN 1 AND 60", name="model_name_length"),
        CheckConstraint("tokens >= 0 AND downgraded >= 0 AND dropped_notes >= 0", name="counts"),
        CheckConstraint("jsonb_typeof(cleaned_codes) = 'array'", name="cleaned_codes_is_list"),
        Index("ix_call_notes_tenant_id_recording_id", "tenant_id", "recording_id"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    recording_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    framework: Mapped[str] = mapped_column(String(10))
    version_no: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(60))
    tokens: Mapped[int] = mapped_column(Integer)
    # Claims the code turned into "unknown" / notes it dropped because a quote was not found.
    downgraded: Mapped[int] = mapped_column(Integer)
    dropped_notes: Mapped[int] = mapped_column(Integer)
    # Kinds of finding (links, instruction-like words...) - never the text itself.
    cleaned_codes: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


_ALL_FIELDS = (rules.NOTE, *rules.ALL_FIELDS)
_PARTS = "value IS NOT NULL AND quote IS NOT NULL AND start_ms IS NOT NULL AND end_ms IS NOT NULL"


class CallNoteLine(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "call_note_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_note_id", "position"),
        ForeignKeyConstraint(
            ["tenant_id", "call_note_id"],
            ["call_notes.tenant_id", "call_notes.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint(_in("field", _ALL_FIELDS), name="field_allowed"),
        CheckConstraint(_in("state", rules.STATES), name="state_allowed"),
        # The three states and what each must (and must not) hold.
        CheckConstraint(
            "(state = 'unknown' AND value IS NULL AND quote IS NULL AND start_ms IS NULL "
            "AND end_ms IS NULL AND reason IS NULL) "
            f"OR (state = 'stated' AND {_PARTS} AND reason IS NULL) "
            f"OR (state = 'assumed' AND {_PARTS} AND reason IS NOT NULL)",
            name="shape_by_state",
        ),
        CheckConstraint("field <> 'note' OR state = 'stated'", name="note_is_stated"),
        CheckConstraint(
            f"start_ms IS NULL OR (start_ms >= 0 AND end_ms > start_ms "
            f"AND end_ms - start_ms <= {rules.MAX_SPAN_MS})",
            name="time_window",
        ),
        CheckConstraint(
            f"value IS NULL OR char_length(value) BETWEEN 1 AND "
            f"CASE WHEN field = 'note' THEN {rules.MAX_NOTE_TEXT} ELSE {rules.MAX_VALUE} END",
            name="value_length",
        ),
        CheckConstraint(
            f"quote IS NULL OR char_length(quote) BETWEEN 1 AND {rules.MAX_QUOTE}",
            name="quote_length",
        ),
        CheckConstraint(
            f"reason IS NULL OR char_length(reason) BETWEEN 1 AND {rules.MAX_REASON}",
            name="reason_length",
        ),
        CheckConstraint(
            "note_code IS NULL OR (state = 'unknown' AND note_code ~ '^[a-z_]{1,40}$')",
            name="note_code_on_unknown",
        ),
        # A checklist field appears once per note; free notes may repeat.
        Index(
            "uq_call_note_lines_tenant_id_call_note_id_field",
            "tenant_id",
            "call_note_id",
            "field",
            unique=True,
            postgresql_where=text("field <> 'note'"),
        ),
    )

    call_note_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(8))
    value: Mapped[str | None] = mapped_column(Text, default=None)
    quote: Mapped[str | None] = mapped_column(Text, default=None)
    start_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    end_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    note_code: Mapped[str | None] = mapped_column(String(40), default=None)


class CallNoteSettings(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    """The organisation's choice of checklist frame: one row each."""

    __tablename__ = "call_note_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("framework", rules.FRAMEWORK_NAMES), name="framework_allowed"),
    )

    framework: Mapped[str] = mapped_column(String(10), default=rules.DEFAULT_FRAMEWORK)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
