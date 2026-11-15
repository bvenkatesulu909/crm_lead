# ruff: noqa: F811 - pytest fixtures imported from the other tests are used as parameters
"""Highlight clips of call recordings through the real database, worker and API (ADR 0033).

A recording is made ready as in test_calls_worker.py (the rep uploads, the worker "cleans" and
"transcribes" it with scripted fakes, 90 seconds long with a short fictional transcript). The clip
service and its worker job then run for real; only ffmpeg (``cut``) is a fake that returns a small
file that depends on the range. People come from test_quotes_api.py (agent1 owns the lead, agent2
does not, a manager reads all, support has no call permissions)."""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.outbox import Job, OutboxJob, PermanentJobError
from app.modules.calls import audio, clips, service
from app.modules.calls.models import CallClip, CallRecording
from app.modules.calls.schemas import ClipCreate, ClipEdit
from tests.db.test_calls_worker import MP3, Setup, setup  # noqa: F401 - fixture used by name
from tests.db.test_quotes_api import Headers, World, api, auth, ok, world  # noqa: F401

CALLS = "/api/v1/leads"


class Cutter:
    """A fake ffmpeg for the clip job: remembers the cuts, can be made to fail."""

    def __init__(self) -> None:
        self.cuts: list[tuple[bytes, int, int]] = []
        self.unreadable = False
        self.tool_missing = False

    def duration_seconds(self, data: bytes, file_name: str) -> float:
        return 90.0

    def clean(self, data: bytes, file_name: str) -> bytes:
        return data

    def cut(self, data: bytes, file_name: str, start_ms: int, end_ms: int) -> bytes:
        if self.tool_missing:
            raise audio.AudioToolMissingError("ffmpeg")
        if self.unreadable:
            raise audio.AudioUnreadableError("broken")
        self.cuts.append((data, start_ms, end_ms))
        return f"ID3clip-{start_ms}-{end_ms}".encode()


def body(start: int = 2_000, end: int = 9_000, title: str = "Budget stated", **more: Any):
    return ClipCreate(start_ms=start, end_ms=end, title=title, **more)


class Ready:
    """A ready recording (90 s) and helpers to make, cut and look at clips."""

    def __init__(self, s: Setup) -> None:
        self.s = s
        self.cutter = Cutter()
        self.recording = s.run(s.queued(language="te").id)
        assert self.recording.status == "ready"

    def clip(self, who: str = "alpha.agent1", **kw: Any):
        principal = self.s.principal(who)
        return clips.create_clip(
            self.s.session, principal, self.s.lead.id, self.recording.id, body(**kw)
        )

    def job(self, clip_id: uuid.UUID, attempt: int = 1) -> Job:
        bind_tenant(self.s.session, self.s.tenant_id)
        rows = self.s.session.scalars(
            select(OutboxJob).where(OutboxJob.kind == clips.JOB_KIND)
        ).all()
        [row] = [r for r in rows if r.payload["clip_id"] == str(clip_id)]
        return Job(row.id, row.tenant_id, row.kind, row.payload, attempt)

    def cut(self, clip_id: uuid.UUID) -> CallClip:
        bind_tenant(self.s.session, self.s.tenant_id)
        clips.process(
            self.s.session,
            self.job(clip_id),
            store=self.s.store,
            cleaner=cast(audio.Cleaner, self.cutter),
        )
        self.s.session.flush()
        return self.row(clip_id)

    def row(self, clip_id: uuid.UUID) -> CallClip:
        bind_tenant(self.s.session, self.s.tenant_id)
        return self.s.session.scalars(
            select(CallClip).where(CallClip.id == clip_id).execution_options(populate_existing=True)
        ).one()


@pytest.fixture
def ready(setup: Setup) -> Ready:
    return Ready(setup)


# --- making a clip ---------------------------------------------------------------------------


def test_a_clip_is_queued_with_its_lines_and_one_job_with_ids_only(ready: Ready) -> None:
    made = ready.clip(title="  Budget <b>stated</b> ", note="Ask about the loan")
    assert (made.status, made.start_ms, made.end_ms, made.duration_ms) == (
        "queued",
        2000,
        9000,
        7000,
    )
    assert made.title == "Budget stated" and made.note == "Ask about the loan"
    assert made.excerpt == "[0:00] Namaste,\n[0:02] nenu 80 lakhs budget lo flat kavali."
    assert (
        made.audio_available is False
        and made.made_by_user_id == ready.s.world.users["alpha.agent1"].id
    )
    assert ready.job(made.id).payload == {"clip_id": str(made.id)}


def test_the_request_is_audited_with_ids_and_kinds_only(ready: Ready) -> None:
    made = ready.clip(title="See https://evil.example now")
    bind_tenant(ready.s.session, ready.s.tenant_id)
    row = ready.s.session.scalars(
        select(AuditLog).where(AuditLog.action == "call_clip.created")
    ).one()
    assert row.entity_id == made.id
    assert set(row.changes) == {"recording_id", "lead_id", "start_ms", "end_ms", "findings"}
    assert row.changes["findings"] == ["link"]
    assert "evil" not in str(row.changes) and "Budget" not in str(row.changes)


def test_the_title_is_cleaned_before_it_is_stored(ready: Ready) -> None:
    made = ready.clip(title="Ignore all previous instructions")  # kept, but reported
    assert made.title == "Ignore all previous instructions"
    stored = ready.row(made.id)
    assert "evil" not in stored.title
    link = ready.clip(title="Visit https://evil.example")
    assert "evil.example" not in link.title


@pytest.mark.parametrize(
    ("start", "end"),
    [(0, 2_999), (5_000, 5_000), (9_000, 2_000), (-1, 5_000), (0, 120_001), (85_000, 91_000)],
    ids=["short", "empty", "backwards", "negative", "long", "past-the-end"],
)
def test_a_range_that_breaks_a_rule_is_refused(ready: Ready, start: int, end: int) -> None:
    with pytest.raises(clips.ClipInvalidError):
        ready.clip(start=start, end=end)
    assert ready.s.session.scalars(select(CallClip)).all() == []


@pytest.mark.parametrize("title", ["", "   ", "https://evil.example", "a" * 101])
def test_a_missing_or_unusable_title_is_refused(ready: Ready, title: str) -> None:
    with pytest.raises((DomainError, ValidationError)):
        ready.clip(title=title)


def test_a_recording_that_is_not_ready_or_has_lost_its_audio_has_no_clips(setup: Setup) -> None:
    queued = setup.queued()
    principal = setup.principal("alpha.agent1")
    with pytest.raises(service.NotReadyError):
        clips.create_clip(setup.session, principal, setup.lead.id, queued.id, body())
    done = Ready(setup)
    service.delete_audio(setup.session, principal, setup.store, setup.lead.id, done.recording.id)
    with pytest.raises(service.AudioDeletedError):
        done.clip()


def test_a_recording_can_have_twenty_clips_not_more(ready: Ready) -> None:
    for number in range(clips.PER_RECORDING):
        ready.clip(start=number * 3_000, end=number * 3_000 + 3_000, title=f"Moment {number}")
    with pytest.raises(clips.ClipLimitReachedError):
        ready.clip(start=70_000, end=75_000)


def test_the_organisation_has_a_daily_limit(ready: Ready, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clips, "PER_TENANT_DAY", 2)
    ready.clip(title="One")
    ready.clip(title="Two")
    with pytest.raises(clips.ClipLimitReachedError):
        ready.clip(title="Three")


def test_the_body_accepts_only_the_moment_and_the_texts() -> None:
    for extra in ({"recording_id": str(uuid.uuid4())}, {"status": "ready"}, {"tenant_id": "x"}):
        with pytest.raises(ValidationError):
            ClipCreate(start_ms=0, end_ms=5000, title="t", **extra)
    for bad in ("1000", 1.5, True, None):
        with pytest.raises(ValidationError):
            ClipCreate(start_ms=bad, end_ms=5000, title="t")


# --- who may reach a clip --------------------------------------------------------------------


def test_someone_who_may_not_read_the_lead_gets_not_found(ready: Ready) -> None:
    other = ready.s.principal("alpha.agent2")
    with pytest.raises(NotFoundError):
        clips.create_clip(ready.s.session, other, ready.s.lead.id, ready.recording.id, body())
    with pytest.raises(NotFoundError):
        clips.list_clips(ready.s.session, other, ready.s.lead.id, ready.recording.id)


def test_another_organisation_gets_not_found(ready: Ready) -> None:
    foreign = ready.s.principal("beta.admin")
    with pytest.raises(NotFoundError):
        clips.list_clips(ready.s.session, foreign, ready.s.lead.id, ready.recording.id)


def test_a_recording_of_another_lead_is_not_found(ready: Ready) -> None:
    principal = ready.s.principal("alpha.agent1")
    with pytest.raises(NotFoundError):
        clips.list_clips(ready.s.session, principal, ready.s.lead.id, uuid.uuid4())


def test_a_clip_of_another_recording_is_not_found_through_this_one(ready: Ready) -> None:
    made = ready.clip()
    second = Ready(ready.s)
    principal = ready.s.principal("alpha.agent1")
    with pytest.raises(clips.ClipNotFoundError):
        clips.edit_clip(
            ready.s.session,
            principal,
            ready.s.lead.id,
            second.recording.id,
            made.id,
            ClipEdit(title="x"),
        )


def test_the_list_is_in_the_order_of_the_call(ready: Ready) -> None:
    ready.clip(start=30_000, end=35_000, title="Later")
    ready.clip(start=2_000, end=6_000, title="Earlier")
    page = clips.list_clips(
        ready.s.session, ready.s.principal("alpha.agent1"), ready.s.lead.id, ready.recording.id
    )
    assert [c.title for c in page.items] == ["Earlier", "Later"]


# --- the worker ------------------------------------------------------------------------------


def test_the_worker_cuts_the_clip_from_the_cleaned_copy_and_stores_it(ready: Ready) -> None:
    made = ready.clip(start=3_000, end=8_500)
    cut = ready.cut(made.id)
    assert cut.status == "ready" and cut.failure_code is None and cut.clip_key
    assert ready.s.store.get(cut.clip_key) == b"ID3clip-3000-8500"
    cleaned = ready.s.store.get(ready.recording.clean_key or "")
    assert ready.cutter.cuts == [(cleaned, 3_000, 8_500)]  # never from the original file
    assert ready.s.store.get(ready.recording.original_key or "") == MP3  # the original is untouched


def test_running_the_job_twice_cuts_once(ready: Ready) -> None:
    made = ready.clip()
    ready.cut(made.id)
    ready.cut(made.id)
    assert len(ready.cutter.cuts) == 1


def test_a_recording_that_lost_its_audio_ends_the_clip_as_failed(ready: Ready) -> None:
    made = ready.clip()
    service.delete_audio(
        ready.s.session,
        ready.s.principal("alpha.agent1"),
        ready.s.store,
        ready.s.lead.id,
        ready.recording.id,
    )
    cut = ready.cut(made.id)
    assert (cut.status, cut.failure_code, cut.clip_key) == ("failed", "audio_deleted", None)
    assert ready.cutter.cuts == []


def test_a_file_that_is_missing_from_the_store_ends_the_clip_as_failed(ready: Ready) -> None:
    made = ready.clip()
    ready.s.store.delete(ready.recording.clean_key or "")
    assert ready.cut(made.id).failure_code == "audio_deleted"


@pytest.mark.parametrize(
    ("flag", "code"), [("unreadable", "unreadable"), ("tool_missing", "audio_tool_missing")]
)
def test_a_cut_that_cannot_work_ends_the_clip_as_failed_with_a_code(
    ready: Ready, flag: str, code: str
) -> None:
    made = ready.clip()
    setattr(ready.cutter, flag, True)
    cut = ready.cut(made.id)
    assert (cut.status, cut.failure_code) == ("failed", code)
    bind_tenant(ready.s.session, ready.s.tenant_id)
    failed = ready.s.session.scalars(
        select(AuditLog).where(AuditLog.action == "call_clip.failed")
    ).one()
    assert failed.changes == {"recording_id": str(ready.recording.id), "code": code}


@pytest.mark.parametrize("payload", [{}, {"clip_id": "not-a-uuid"}, {"clip_id": str(uuid.uuid4())}])
def test_a_job_with_a_bad_or_unknown_clip_is_dead_not_retried(ready: Ready, payload: Any) -> None:
    job = Job(uuid.uuid4(), ready.s.tenant_id, clips.JOB_KIND, payload, 1)
    with pytest.raises(PermanentJobError):
        clips.process(
            ready.s.session, job, store=ready.s.store, cleaner=cast(audio.Cleaner, ready.cutter)
        )


def test_the_dead_job_hook_fails_a_clip_that_is_still_queued_only(ready: Ready) -> None:
    waiting, done = ready.clip(title="Waiting"), ready.clip(start=20_000, end=25_000, title="Done")
    ready.cut(done.id)
    for clip in (waiting, done):
        clips.on_dead(ready.s.session, ready.job(clip.id, attempt=5), "boom")
    ready.s.session.flush()
    assert (ready.row(waiting.id).status, ready.row(waiting.id).failure_code) == (
        "failed",
        "processing_failed",
    )
    assert ready.row(done.id).status == "ready"


# --- listening, editing, deleting ------------------------------------------------------------


def test_a_ready_clip_has_a_signed_link_with_a_fixed_name(ready: Ready) -> None:
    made = ready.clip(title="Secret title")
    ready.cut(made.id)
    link = clips.listen_clip(
        ready.s.session,
        ready.s.principal("alpha.agent1"),
        ready.s.store,
        ready.s.lead.id,
        ready.recording.id,
        made.id,
    )
    assert link.expires_in_seconds == 60 and "clip-2000-9000.mp3" in link.url
    assert "Secret" not in link.url


def test_a_clip_that_is_not_ready_or_lost_its_audio_cannot_be_listened_to(ready: Ready) -> None:
    made = ready.clip()
    principal = ready.s.principal("alpha.agent1")
    with pytest.raises(service.NotReadyError):
        clips.listen_clip(
            ready.s.session, principal, ready.s.store, ready.s.lead.id, ready.recording.id, made.id
        )
    ready.cut(made.id)
    service.delete_audio(
        ready.s.session, principal, ready.s.store, ready.s.lead.id, ready.recording.id
    )
    with pytest.raises(service.AudioDeletedError):
        clips.listen_clip(
            ready.s.session, principal, ready.s.store, ready.s.lead.id, ready.recording.id, made.id
        )


def test_the_maker_and_a_manager_may_edit_but_the_lead_owner_may_not(ready: Ready) -> None:
    made = ready.clip("alpha.manager", title="By the manager")  # a manager reads every lead
    session, lead, rec = ready.s.session, ready.s.lead.id, ready.recording.id
    owner = ready.s.principal("alpha.agent1")
    with pytest.raises(ForbiddenError):
        clips.edit_clip(session, owner, lead, rec, made.id, ClipEdit(title="Mine now"))
    manager = ready.s.principal("alpha.manager2")
    edited = clips.edit_clip(
        session, manager, lead, rec, made.id, ClipEdit(title="Better", note="n")
    )
    assert (edited.title, edited.note) == ("Better", "n")
    mine = ready.clip(title="Mine")
    assert clips.edit_clip(session, owner, lead, rec, mine.id, ClipEdit(note=None)).note is None


def test_an_edit_is_cleaned_audited_without_the_text_and_never_empties_the_title(
    ready: Ready,
) -> None:
    made = ready.clip()
    principal = ready.s.principal("alpha.agent1")
    session, lead, rec = ready.s.session, ready.s.lead.id, ready.recording.id
    out = clips.edit_clip(
        session, principal, lead, rec, made.id, ClipEdit(title="<i>New</i> https://x.y")
    )
    assert "x.y" not in out.title and out.title.startswith("New")
    with pytest.raises(clips.ClipInvalidError):
        clips.edit_clip(session, principal, lead, rec, made.id, ClipEdit(title="   "))
    with pytest.raises(clips.ClipInvalidError):
        clips.edit_clip(session, principal, lead, rec, made.id, ClipEdit())
    bind_tenant(session, ready.s.tenant_id)
    row = session.scalars(select(AuditLog).where(AuditLog.action == "call_clip.edited")).one()
    assert set(row.changes) == {"recording_id", "lead_id", "fields", "findings"}
    assert row.changes["fields"] == ["title"] and "New" not in str(row.changes)


def test_deleting_a_clip_removes_its_row_and_its_file(ready: Ready) -> None:
    made = ready.clip()
    key = ready.cut(made.id).clip_key or ""
    clips.delete_clip(
        ready.s.session,
        ready.s.principal("alpha.agent1"),
        ready.s.store,
        ready.s.lead.id,
        ready.recording.id,
        made.id,
    )
    ready.s.session.flush()
    assert ready.s.session.get(CallClip, made.id) is None
    assert key not in ready.s.store.objects
    bind_tenant(ready.s.session, ready.s.tenant_id)
    assert ready.s.session.scalars(
        select(AuditLog).where(AuditLog.action == "call_clip.deleted")
    ).one()


def test_the_lead_owner_cannot_delete_a_managers_clip(ready: Ready) -> None:
    made = ready.clip("alpha.manager")
    with pytest.raises(ForbiddenError):
        clips.delete_clip(
            ready.s.session,
            ready.s.principal("alpha.agent1"),
            ready.s.store,
            ready.s.lead.id,
            ready.recording.id,
            made.id,
        )


# --- retention -------------------------------------------------------------------------------


def test_deleting_the_recordings_audio_deletes_the_clips_audio_and_keeps_the_words(
    ready: Ready,
) -> None:
    made = ready.clip(title="Keep my words")
    key = ready.cut(made.id).clip_key or ""
    service.delete_audio(
        ready.s.session,
        ready.s.principal("alpha.agent1"),
        ready.s.store,
        ready.s.lead.id,
        ready.recording.id,
    )
    kept = ready.row(made.id)
    assert kept.audio_deleted_at is not None and kept.title == "Keep my words" and kept.excerpt
    assert key not in ready.s.store.objects


def test_the_retention_sweep_does_the_same(ready: Ready) -> None:
    made = ready.clip()
    key = ready.cut(made.id).clip_key or ""
    when = datetime(2036, 1, 1, tzinfo=UTC)
    gone = service.delete_old_audio(
        ready.s.session, ready.s.store, when, tenant_id=ready.s.tenant_id, retention_days=90
    )
    assert gone == 1 and ready.row(made.id).audio_deleted_at is not None
    assert key not in ready.s.store.objects


# --- what the database itself refuses --------------------------------------------------------


def test_the_database_keeps_the_range_excerpt_maker_and_recording_fixed(ready: Ready) -> None:
    made = ready.clip()
    session = ready.s.session
    for statement in (
        "UPDATE call_clips SET start_ms = 1000 WHERE id = :i",
        "UPDATE call_clips SET end_ms = 20000 WHERE id = :i",
        "UPDATE call_clips SET excerpt = 'changed' WHERE id = :i",
        "UPDATE call_clips SET made_by_user_id = gen_random_uuid() WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="cannot change"), session.begin_nested():
            session.execute(text(statement), {"i": made.id})
    # The title, note and file fields may change.
    session.execute(text("UPDATE call_clips SET title = 'ok' WHERE id = :i"), {"i": made.id})


@pytest.mark.parametrize(
    "values",
    [
        {"start_ms": 0, "end_ms": 2_000, "title": "t"},
        {"start_ms": 0, "end_ms": 130_000, "title": "t"},
        {"start_ms": 0, "end_ms": 5_000, "title": ""},
        {"start_ms": 0, "end_ms": 5_000, "title": "a" * 101},
        {"start_ms": 0, "end_ms": 5_000, "title": "t", "note": "a" * 501},
        {"start_ms": 0, "end_ms": 5_000, "title": "t", "status": "ready"},
        {"start_ms": 0, "end_ms": 5_000, "title": "t", "status": "failed"},
        {"start_ms": 0, "end_ms": 5_000, "title": "t", "status": "done"},
        {"start_ms": 0, "end_ms": 5_000, "title": "t", "failure_code": "x"},
    ],
    ids=[
        "short",
        "long",
        "no-title",
        "long-title",
        "long-note",
        "ready-no-file",
        "failed-no-code",
        "odd-status",
        "code-without-failure",
    ],
)
def test_the_database_refuses_a_bad_clip(ready: Ready, values: dict[str, Any]) -> None:
    session = ready.s.session
    bind_tenant(session, ready.s.tenant_id)
    with pytest.raises((IntegrityError, DBAPIError)), session.begin_nested():
        session.add(
            CallClip(
                tenant_id=ready.s.tenant_id,
                recording_id=ready.recording.id,
                made_by_user_id=ready.s.world.users["alpha.agent1"].id,
                **values,
            )
        )
        session.flush()


def test_a_clip_cannot_point_at_another_organisations_recording(ready: Ready) -> None:
    session = ready.s.session
    foreign = ready.s.world.users["beta.admin"]
    bind_tenant(session, foreign.tenant_id)
    with pytest.raises((IntegrityError, DBAPIError)), session.begin_nested():
        session.add(
            CallClip(
                tenant_id=foreign.tenant_id,
                recording_id=ready.recording.id,
                made_by_user_id=foreign.id,
                start_ms=0,
                end_ms=5_000,
                title="t",
            )
        )
        session.flush()


def test_the_worker_knows_the_clip_job_and_its_dead_job_hook() -> None:
    from app.worker import dead_job_handlers

    assert clips.JOB_KIND in dead_job_handlers()


# --- the API ---------------------------------------------------------------------------------


def url(ready: Ready, tail: str = "") -> str:
    return f"{CALLS}/{ready.s.lead.id}/calls/{ready.recording.id}/clips{tail}"


def test_the_api_makes_lists_edits_listens_and_deletes(
    api: TestClient, auth: Headers, ready: Ready
) -> None:
    api.app.state.file_store = ready.s.store  # type: ignore[attr-defined]
    me = auth("alpha.agent1")
    made = ok(
        api.post(
            url(ready), json={"start_ms": 2000, "end_ms": 9000, "title": "Budget"}, headers=me
        ),
        201,
    )
    assert made["status"] == "queued" and made["lead_id"] == str(ready.s.lead.id)
    assert [c["id"] for c in ok(api.get(url(ready), headers=me))["items"]] == [made["id"]]
    assert api.get(url(ready, f"/{made['id']}/listen"), headers=me).status_code == 409
    ready.cut(uuid.UUID(made["id"]))
    assert (
        "clip-2000-9000.mp3" in ok(api.get(url(ready, f"/{made['id']}/listen"), headers=me))["url"]
    )
    assert (
        ok(api.patch(url(ready, f"/{made['id']}"), json={"title": "Better"}, headers=me))["title"]
        == "Better"
    )
    assert api.delete(url(ready, f"/{made['id']}"), headers=me).status_code == 204
    assert ok(api.get(url(ready), headers=me))["items"] == []


@pytest.mark.parametrize(
    ("user", "expected"),
    [("alpha.agent2", 404), ("beta.admin", 404), ("alpha.support", 403), ("alpha.customer", 403)],
)
def test_who_may_not_use_the_clip_endpoints(
    api: TestClient, auth: Headers, ready: Ready, user: str, expected: int
) -> None:
    made = ready.clip()
    headers = auth(user)
    payload = {"start_ms": 2000, "end_ms": 9000, "title": "x"}
    assert api.post(url(ready), json=payload, headers=headers).status_code == expected
    assert api.get(url(ready), headers=headers).status_code == expected
    assert api.get(url(ready, f"/{made.id}/listen"), headers=headers).status_code == expected
    assert (
        api.patch(url(ready, f"/{made.id}"), json={"title": "y"}, headers=headers).status_code
        == expected
    )
    assert api.delete(url(ready, f"/{made.id}"), headers=headers).status_code == expected


def test_every_clip_endpoint_needs_a_sign_in(api: TestClient, ready: Ready) -> None:
    some = uuid.uuid4()
    assert api.post(url(ready), json={}).status_code == 401
    assert api.get(url(ready)).status_code == 401
    assert api.get(url(ready, f"/{some}/listen")).status_code == 401
    assert api.patch(url(ready, f"/{some}"), json={}).status_code == 401
    assert api.delete(url(ready, f"/{some}")).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"start_ms": 2000, "end_ms": 9000, "title": "t", "tenant_id": str(uuid.uuid4())},
        {"start_ms": 2000, "end_ms": 9000, "title": "t", "status": "ready"},
        {"start_ms": 2000, "end_ms": 9000, "title": "t", "recording_id": str(uuid.uuid4())},
        {"start_ms": "2000", "end_ms": 9000, "title": "t"},
        {"start_ms": 2000.5, "end_ms": 9000, "title": "t"},
        {"end_ms": 9000, "title": "t"},
    ],
)
def test_the_body_cannot_name_the_organisation_status_or_recording(
    api: TestClient, auth: Headers, ready: Ready, payload: dict[str, Any]
) -> None:
    assert api.post(url(ready), json=payload, headers=auth("alpha.agent1")).status_code == 422
    assert ready.s.session.scalars(select(CallClip)).all() == []


def test_a_range_error_is_a_clear_422(api: TestClient, auth: Headers, ready: Ready) -> None:
    response = api.post(
        url(ready), json={"start_ms": 0, "end_ms": 1000, "title": "t"}, headers=auth("alpha.agent1")
    )
    assert response.status_code == 422 and response.json()["code"] == "clip_invalid"
    assert isinstance(ready.recording, CallRecording)
