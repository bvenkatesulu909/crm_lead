# ruff: noqa: F811, S608 - pytest fixtures are imported and used as parameters; SQL is constants
"""The tables of the call notes (ADR 0035, CN1) through the real database: forced row-level
security, the three line states enforced by the database itself, insert-only rows, one settings row
per organisation. A ready recording comes from test_calls_worker.py (scripted fakes)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.call_notes import rules
from app.modules.call_notes.models import CallNote, CallNoteLine, CallNoteSettings
from app.modules.calls.models import CallRecording
from tests.db.test_approvals import add_lead
from tests.db.test_calls_worker import Setup, setup  # noqa: F401 - fixture used by name
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name


def make_note(s: Setup, **changes: Any) -> CallNote:
    recording = s.run(s.queued().id)
    bind_tenant(s.session, s.tenant_id)
    values: dict[str, Any] = {
        "tenant_id": s.tenant_id,
        "recording_id": recording.id,
        "lead_id": s.lead.id,
        "requested_by_user_id": s.world.users["alpha.agent1"].id,
        "framework": "bant",
        "version_no": 1,
        "model_name": "scripted",
        "tokens": 120,
        "downgraded": 0,
        "dropped_notes": 0,
        "cleaned_codes": [],
    }
    note = CallNote(**{**values, **changes})
    s.session.add(note)
    s.session.flush()
    return note


def line_for(note: CallNote, **changes: Any) -> CallNoteLine:
    values: dict[str, Any] = {
        "tenant_id": note.tenant_id,
        "call_note_id": note.id,
        "position": 1,
        "field": "budget",
        "state": "stated",
        "value": "around one and a half crore",
        "quote": "My budget is around one and a half crore",
        "start_ms": 6_000,
        "end_ms": 14_000,
    }
    return CallNoteLine(**{**values, **changes})


def add_line(s: Setup, note: CallNote, **changes: Any) -> CallNoteLine:
    row = line_for(note, **changes)
    s.session.add(row)
    s.session.flush()
    return row


def test_a_note_and_its_lines_are_stored_and_read_back(setup: Setup) -> None:
    note = make_note(setup)
    add_line(setup, note)
    add_line(
        setup,
        note,
        position=2,
        field="authority",
        state="assumed",
        value="wife decides too",
        reason="They said 'we decide together'.",
        quote="My wife and I decide together",
        start_ms=14_000,
        end_ms=22_000,
    )
    add_line(
        setup,
        note,
        position=3,
        field="need",
        state="unknown",
        value=None,
        quote=None,
        start_ms=None,
        end_ms=None,
        note_code="quote_not_found",
    )
    add_line(setup, note, position=4, field="note", value="Wants a flat near Kokapet")
    rows = setup.session.scalars(
        select(CallNoteLine).where(CallNoteLine.call_note_id == note.id).order_by("position")
    ).all()
    assert [(r.field, r.state) for r in rows] == [
        ("budget", "stated"),
        ("authority", "assumed"),
        ("need", "unknown"),
        ("note", "stated"),
    ]
    assert note.seq >= 1 and note.created_at is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "guessed"},
        {"field": "price"},
        {"field": "note", "state": "assumed", "reason": "why"},
        {"state": "unknown"},  # still holds a value and a quote
        {"value": None},
        {"quote": None},
        {"start_ms": None},
        {"end_ms": None},
        {"reason": "a stated line has no reason"},
        {"state": "assumed"},  # assumed without a reason
        {"state": "assumed", "reason": "why", "quote": None},
        {"start_ms": 14_000, "end_ms": 6_000},
        {"start_ms": 6_000, "end_ms": 6_000},
        {"start_ms": -1},
        {"end_ms": 6_000 + rules.MAX_SPAN_MS + 1},
        {"value": "v" * (rules.MAX_VALUE + 1)},
        {"quote": "q" * (rules.MAX_QUOTE + 1)},
        {"state": "assumed", "reason": "r" * (rules.MAX_REASON + 1)},
        {"note_code": "quote_not_found"},  # a code belongs on an unknown line only
        {"position": 0},
        {"value": ""},
        {"quote": ""},
    ],
    ids=[
        "state-not-allowed",
        "field-not-allowed",
        "note-line-assumed",
        "unknown-holding-data",
        "stated-no-value",
        "stated-no-quote",
        "stated-no-start",
        "stated-no-end",
        "stated-with-reason",
        "assumed-no-reason",
        "assumed-no-quote",
        "backwards",
        "empty-window",
        "negative-start",
        "window-too-long",
        "long-value",
        "long-quote",
        "long-reason",
        "code-on-stated",
        "position-zero",
        "empty-value",
        "empty-quote",
    ],
)
def test_the_database_itself_refuses_a_line_outside_the_three_states(
    setup: Setup, changes: dict[str, Any]
) -> None:
    note = make_note(setup)
    with pytest.raises((IntegrityError, DBAPIError)), setup.session.begin_nested():
        add_line(setup, note, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"note_code": "Quote Not Found!"},
        {"value": "v", "note_code": None},
    ],
    ids=["code-shape", "unknown-with-value"],
)
def test_an_unknown_line_may_hold_only_a_code(setup: Setup, changes: dict[str, Any]) -> None:
    note = make_note(setup)
    base: dict[str, Any] = {
        "state": "unknown",
        "value": None,
        "quote": None,
        "start_ms": None,
        "end_ms": None,
    }
    with pytest.raises((IntegrityError, DBAPIError)), setup.session.begin_nested():
        add_line(setup, note, **{**base, **changes})
    add_line(setup, note, **base)  # the clean unknown line is accepted


def test_every_checklist_field_of_both_frames_is_accepted(setup: Setup) -> None:
    note = make_note(setup)
    for position, key in enumerate(rules.ALL_FIELDS, start=1):
        add_line(setup, note, position=position, field=key)


def test_a_field_appears_once_per_note_but_notes_may_repeat(setup: Setup) -> None:
    note = make_note(setup)
    add_line(setup, note)
    with pytest.raises(IntegrityError), setup.session.begin_nested():
        add_line(setup, note, position=2)  # the budget again
    add_line(setup, note, position=2, field="note", value="one")
    add_line(setup, note, position=3, field="note", value="two")


def test_a_position_is_used_once_per_note(setup: Setup) -> None:
    note = make_note(setup)
    add_line(setup, note)
    with pytest.raises(IntegrityError), setup.session.begin_nested():
        add_line(setup, note, field="need")


@pytest.mark.parametrize(
    "changes",
    [
        {"framework": "spin"},
        {"framework": ""},
        {"version_no": 0},
        {"tokens": -1},
        {"downgraded": -1},
        {"dropped_notes": -1},
        {"cleaned_codes": {"link": True}},
        {"model_name": ""},
    ],
    ids=[
        "framework",
        "no-framework",
        "version-zero",
        "tokens",
        "downgraded",
        "dropped",
        "codes",
        "model",
    ],
)
def test_the_database_refuses_a_bad_header(setup: Setup, changes: dict[str, Any]) -> None:
    with pytest.raises((IntegrityError, DBAPIError)), setup.session.begin_nested():
        make_note(setup, **changes)


def test_both_frames_are_accepted_and_a_version_is_used_once_per_recording(setup: Setup) -> None:
    first = make_note(setup, framework="meddic")
    assert first.framework == "meddic"
    with pytest.raises(IntegrityError), setup.session.begin_nested():
        setup.session.add(
            CallNote(
                tenant_id=setup.tenant_id,
                recording_id=first.recording_id,
                lead_id=setup.lead.id,
                requested_by_user_id=first.requested_by_user_id,
                framework="bant",
                version_no=1,
                model_name="scripted",
                tokens=1,
                downgraded=0,
                dropped_notes=0,
                cleaned_codes=[],
            )
        )
        setup.session.flush()


@pytest.fixture
def owner_world(committed_world: Session, world: World) -> Iterator[tuple[Session, World]]:
    """The owner's session (it may UPDATE, so the TRIGGER is what is tested, not the privilege).
    Rows are left uncommitted; end the transaction before the fixtures clean the tables."""
    yield committed_world, world
    committed_world.rollback()


def test_rows_can_never_be_changed_or_deleted_early(
    owner_world: tuple[Session, World],
) -> None:
    session, world = owner_world
    person = world.users["alpha.agent1"]
    bind_tenant(session, person.tenant_id)
    lead = add_lead(session, world)
    recording = CallRecording(
        tenant_id=person.tenant_id,
        lead_id=lead.id,
        added_by_user_id=person.id,
        language="en",
        consent_confirmed_at=datetime.now(UTC),
        file_name="call.mp3",
        content_type="audio/mpeg",
        declared_size=10,
        status="ready",
        original_key="calls/original.mp3",
        transcript_text="My budget is around one and a half crore.",
        transcript_segments=[],
    )
    session.add(recording)
    session.flush()
    note = CallNote(
        tenant_id=person.tenant_id,
        recording_id=recording.id,
        lead_id=lead.id,
        requested_by_user_id=person.id,
        framework="bant",
        version_no=1,
        model_name="scripted",
        tokens=1,
        downgraded=0,
        dropped_notes=0,
        cleaned_codes=[],
    )
    session.add(note)
    session.flush()
    line = line_for(note)
    session.add(line)
    session.flush()
    for statement, key in (
        ("UPDATE call_notes SET framework = 'meddic' WHERE id = :i", note.id),
        ("UPDATE call_notes SET tokens = 0 WHERE id = :i", note.id),
        ("UPDATE call_note_lines SET value = 'changed' WHERE id = :i", line.id),
        ("UPDATE call_note_lines SET state = 'unknown' WHERE id = :i", line.id),
    ):
        with pytest.raises(DBAPIError, match="cannot be changed"), session.begin_nested():
            session.execute(text(statement), {"i": key})
    for table, key in (("call_note_lines", line.id), ("call_notes", note.id)):
        with pytest.raises(DBAPIError, match="only after 365 days"), session.begin_nested():
            session.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": key})


def test_a_line_cannot_point_at_another_organisations_note(setup: Setup) -> None:
    note = make_note(setup)
    foreign = setup.world.users["beta.admin"].tenant_id
    bind_tenant(setup.session, foreign)
    with pytest.raises((IntegrityError, DBAPIError)), setup.session.begin_nested():
        setup.session.add(line_for(note, tenant_id=foreign))
        setup.session.flush()


def test_a_note_cannot_point_at_another_organisations_recording(setup: Setup) -> None:
    recording = setup.run(setup.queued().id)
    foreign_user = setup.world.users["beta.admin"]
    bind_tenant(setup.session, foreign_user.tenant_id)
    with pytest.raises((IntegrityError, DBAPIError)), setup.session.begin_nested():
        setup.session.add(
            CallNote(
                tenant_id=foreign_user.tenant_id,
                recording_id=recording.id,
                lead_id=setup.lead.id,
                requested_by_user_id=foreign_user.id,
                framework="bant",
                version_no=1,
                model_name="scripted",
                tokens=1,
                downgraded=0,
                dropped_notes=0,
                cleaned_codes=[],
            )
        )
        setup.session.flush()


def test_two_organisations_never_see_each_others_notes(setup: Setup) -> None:
    note = make_note(setup)
    add_line(setup, note)
    setup.session.flush()
    bind_tenant(setup.session, setup.world.users["beta.admin"].tenant_id)
    assert setup.session.scalars(select(CallNote)).all() == []
    assert setup.session.scalars(select(CallNoteLine)).all() == []
    bind_tenant(setup.session, setup.tenant_id)
    assert len(setup.session.scalars(select(CallNote)).all()) == 1


def test_the_application_role_cannot_update_or_truncate_the_notes(setup: Setup) -> None:
    for table in ("call_notes", "call_note_lines"):
        grants = {
            row[0]
            for row in setup.session.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = :t AND grantee = 'crm_app'"
                ),
                {"t": table},
            )
        }
        assert "UPDATE" not in grants and "TRUNCATE" not in grants
        assert {"SELECT", "INSERT"} <= grants


# --- the organisation's choice of frame ---------------------------------------------------------


def settings_row(s: Setup, tenant_id: uuid.UUID | None = None, **changes: Any) -> CallNoteSettings:
    tenant = tenant_id or s.tenant_id
    bind_tenant(s.session, tenant)
    row = CallNoteSettings(
        tenant_id=tenant, framework="meddic", updated_by_user_id=s.world.users["alpha.admin"].id
    )
    for name, value in changes.items():
        setattr(row, name, value)
    s.session.add(row)
    s.session.flush()
    return row


def test_an_organisation_has_one_settings_row_and_the_frame_can_change(setup: Setup) -> None:
    row = settings_row(setup)
    assert (row.framework, row.version) == ("meddic", 1)
    row.framework = "bant"
    setup.session.flush()
    assert row.version == 2
    with pytest.raises(IntegrityError), setup.session.begin_nested():
        settings_row(setup)


def test_the_settings_frame_must_be_one_of_the_two(setup: Setup) -> None:
    with pytest.raises((IntegrityError, DBAPIError)), setup.session.begin_nested():
        settings_row(setup, framework="spin")


def test_settings_of_one_organisation_are_invisible_to_another(setup: Setup) -> None:
    settings_row(setup)
    bind_tenant(setup.session, setup.world.users["beta.admin"].tenant_id)
    assert setup.session.scalars(select(CallNoteSettings)).all() == []
