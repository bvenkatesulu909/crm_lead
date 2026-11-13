# ruff: noqa: F811 - pytest fixtures imported from test_leads_api are used as parameters
"""Call recordings (ADR 0030, step CA1) through the real API and database: start -> the browser
sends the file to the store -> finish. The file store is the in-memory one, whose ``browser_upload``
refuses what a real store refuses for a signed POST policy (another key, a bigger body).

tenant ALPHA: admin, manager, agent1, agent2 (sales agents), support (support_agent), customer.
tenant BETA: admin, agent. A lead of agent1 is the main character.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.storage import MemoryFileStore, pending_key
from app.modules.calls import service
from app.modules.calls.models import CallRecording
from tests.db.test_leads_api import Headers, api, auth, create, people  # noqa: F401 - fixtures

LEADS = "/api/v1/leads"
AGENT = "alpha.agent1"
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x01" * 2000
PDF = b"%PDF-1.7 a fictional document " + b"\x01" * 200


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


@pytest.fixture
def settings_override(api: TestClient):  # noqa: ANN201
    """Change the API's settings for one test and put them back afterwards."""
    original = api.app.state.settings  # type: ignore[attr-defined]

    def change(**values: Any) -> None:
        api.app.state.settings = original.model_copy(update=values)  # type: ignore[attr-defined]

    yield change
    api.app.state.settings = original  # type: ignore[attr-defined]


def switch(api: TestClient, auth: Headers, on: bool = True) -> None:
    url = "/api/v1/agents/call_audio"
    current = api.get(url, headers=auth("alpha.admin")).json()
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    response = api.patch(url, json=body, headers=auth("alpha.admin"))
    assert response.status_code == 200, response.text


@pytest.fixture
def lead(api, auth) -> dict[str, Any]:
    return create(api, auth, AGENT, last_name="Rao")


@pytest.fixture
def on(api, auth) -> None:
    switch(api, auth)


def calls(lead_id: str, tail: str = "") -> str:
    return f"{LEADS}/{lead_id}/calls{tail}"


def start(api, auth, lead_id: str, /, user: str = AGENT, **changes: Any) -> Any:
    body = {
        "file_name": "call 12 nov.mp3",
        "size_bytes": len(MP3),
        "language": "hi",
        "consent": True,
        **changes,
    }
    return api.post(calls(lead_id, "/uploads"), json=body, headers=auth(user))


def finish(api, auth, lead_id: str, call_id: str, user: str = AGENT) -> Any:
    return api.post(calls(lead_id, f"/{call_id}/finish"), headers=auth(user))


def upload(
    api, auth, files: MemoryFileStore, lead_id: str, data: bytes = MP3, /, **changes: Any
) -> dict[str, Any]:
    """Start, send the file the way a browser does, finish; returns the finished recording."""
    started = start(api, auth, lead_id, **{"size_bytes": len(data), **changes})
    assert started.status_code == 201, started.text
    ticket = started.json()
    key = ticket["fields"]["key"]
    assert files.browser_upload(key, data)
    done = finish(api, auth, lead_id, ticket["call_id"])
    assert done.status_code == 200, done.text
    body: dict[str, Any] = done.json()
    return body


# --- the switch ---------------------------------------------------------------------------------


def test_call_recordings_are_off_until_an_administrator_switches_them_on(
    api, auth, lead, files
) -> None:
    refused = start(api, auth, lead["id"])
    assert refused.status_code == 503
    assert refused.json()["code"] == "call_audio_unavailable"
    switch(api, auth, True)
    assert start(api, auth, lead["id"]).status_code == 201
    switch(api, auth, False)
    assert start(api, auth, lead["id"]).status_code == 503


# --- the happy path -----------------------------------------------------------------------------


def test_a_recording_goes_start_send_finish_and_is_queued_for_processing(
    api, auth, lead, files, on, db_session: Session
) -> None:
    started = start(api, auth, lead["id"])
    assert started.status_code == 201, started.text
    ticket = started.json()
    assert set(ticket) == {"call_id", "url", "fields", "expires_at", "max_bytes"}
    key = ticket["fields"]["key"]
    assert key == pending_key(
        uuid.UUID(_tenant_of(db_session, ticket["call_id"])), uuid.UUID(ticket["call_id"])
    )
    assert files.signed_uploads[key] == ("audio/mpeg", len(MP3))

    assert files.browser_upload(key, MP3)
    done = finish(api, auth, lead["id"], ticket["call_id"])
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["status"], body["language"], body["size_bytes"]) == ("queued", "hi", len(MP3))
    assert body["has_transcript"] is False and body["failure_code"] is None
    assert body["audio_available"] is True and body["consent_confirmed_at"]

    original = [k for k in files.objects if k.startswith("tenant/") and "/calls/" in k]
    assert len(original) == 1 and files.get(original[0]) == MP3
    assert files.stat(original[0]).content_type == "audio/mpeg"
    assert key not in files.objects  # the pending copy is gone


def _tenant_of(db_session: Session, call_id: str) -> str:
    row = db_session.scalars(
        select(CallRecording).where(CallRecording.id == uuid.UUID(call_id))
    ).one()
    return str(row.tenant_id)


def test_the_list_and_the_detail_show_the_recording(api, auth, lead, files, on) -> None:
    done = upload(api, auth, files, lead["id"])
    listed = api.get(calls(lead["id"]), headers=auth(AGENT)).json()
    assert [c["id"] for c in listed["items"]] == [done["id"]]
    assert "transcript" not in listed["items"][0]  # the list is light
    detail = api.get(calls(lead["id"], f"/{done['id']}"), headers=auth(AGENT))
    assert detail.status_code == 200 and detail.json()["id"] == done["id"]
    assert "transcript" in detail.json()


def test_a_new_recording_is_listed_newest_first(api, auth, lead, files, on) -> None:
    first = upload(api, auth, files, lead["id"])
    second = upload(api, auth, files, lead["id"])
    ids = [c["id"] for c in api.get(calls(lead["id"]), headers=auth(AGENT)).json()["items"]]
    assert ids == [second["id"], first["id"]]


def test_adding_a_recording_is_audited_with_ids_only(
    api, auth, lead, files, on, db_session: Session
) -> None:
    done = upload(api, auth, files, lead["id"], language="te")
    rows = [
        r
        for r in db_session.scalars(select(AuditLog).where(AuditLog.action == "call.added"))
        if r.entity_id == uuid.UUID(done["id"])
    ]
    assert len(rows) == 1
    assert rows[0].changes == {"lead_id": lead["id"], "language": "te"}


# --- consent, language, type, size --------------------------------------------------------------


@pytest.mark.parametrize("consent", [False, None, "yes", 1])
def test_without_the_buyers_consent_nothing_is_accepted(
    api, auth, lead, files, on, consent
) -> None:
    assert start(api, auth, lead["id"], consent=consent).status_code == 422


def test_the_consent_field_is_required(api, auth, lead, files, on) -> None:
    body = {"file_name": "a.mp3", "size_bytes": 10, "language": "hi"}
    assert (
        api.post(calls(lead["id"], "/uploads"), json=body, headers=auth(AGENT)).status_code == 422
    )


@pytest.mark.parametrize("language", ["fr", "HI", "", "hindi", None])
def test_only_three_languages_are_accepted(api, auth, lead, files, on, language) -> None:
    assert start(api, auth, lead["id"], language=language).status_code == 422


@pytest.mark.parametrize(
    "name", ["call.exe", "call.pdf", "call", ".mp3", "call.mp3.exe", "call.zip"]
)
def test_only_audio_names_are_accepted(api, auth, lead, files, on, name) -> None:
    response = start(api, auth, lead["id"], file_name=name)
    assert response.status_code == 422, response.text


def test_a_recording_over_the_size_limit_is_refused_before_any_link_is_given(
    api, auth, lead, files, on, settings_override
) -> None:
    settings_override(calls_max_bytes=1_000_000)
    response = start(api, auth, lead["id"], size_bytes=1_000_001)
    assert response.status_code == 413 and response.json()["code"] == "call_too_large"
    assert files.signed_uploads == {}


def test_an_empty_size_is_refused(api, auth, lead, files, on) -> None:
    assert start(api, auth, lead["id"], size_bytes=0).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": str(uuid.uuid4())},
        {"lead_id": str(uuid.uuid4())},
        {"status": "ready"},
        {"added_by_user_id": str(uuid.uuid4())},
        {"transcript": "I wrote this myself"},
        {"original_key": "tenant/x/calls/y/z"},
    ],
)
def test_what_the_server_decides_cannot_be_sent(api, auth, lead, files, on, extra) -> None:
    assert start(api, auth, lead["id"], **extra).status_code == 422


# --- finishing ----------------------------------------------------------------------------------


def test_finishing_before_the_file_arrived_says_so_and_can_be_retried(
    api, auth, lead, files, on
) -> None:
    ticket = start(api, auth, lead["id"]).json()
    early = finish(api, auth, lead["id"], ticket["call_id"])
    assert early.status_code == 409 and early.json()["code"] == "call_not_received"
    assert files.browser_upload(ticket["fields"]["key"], MP3)
    assert finish(api, auth, lead["id"], ticket["call_id"]).status_code == 200


def test_a_recording_can_be_finished_only_once(api, auth, lead, files, on) -> None:
    done = upload(api, auth, files, lead["id"])
    again = finish(api, auth, lead["id"], done["id"])
    assert again.status_code == 404


def test_a_file_that_is_not_audio_is_refused_and_not_kept(api, auth, lead, files, on) -> None:
    ticket = start(api, auth, lead["id"], size_bytes=len(PDF), file_name="call.mp3").json()
    key = ticket["fields"]["key"]
    assert files.browser_upload(key, PDF)
    refused = finish(api, auth, lead["id"], ticket["call_id"])
    assert refused.status_code == 422 and refused.json()["code"] == "call_not_audio"
    assert key not in files.objects
    assert not [k for k in files.objects if "/calls/" in k]
    shown = api.get(calls(lead["id"], f"/{ticket['call_id']}"), headers=auth(AGENT)).json()
    assert (shown["status"], shown["failure_code"]) == ("failed", "not_audio")
    assert shown["audio_available"] is False


def test_audio_of_another_type_under_the_wrong_name_is_refused(api, auth, lead, files, on) -> None:
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x01" * 400
    ticket = start(api, auth, lead["id"], size_bytes=len(wav), file_name="call.mp3").json()
    assert files.browser_upload(ticket["fields"]["key"], wav)
    assert finish(api, auth, lead["id"], ticket["call_id"]).status_code == 422


def test_a_file_bigger_than_announced_is_refused_and_removed(api, auth, lead, files, on) -> None:
    ticket = start(api, auth, lead["id"]).json()
    key = ticket["fields"]["key"]
    files.put(key, MP3 + b"\x01" * 50_000, "audio/mpeg")  # a store that does not enforce the policy
    response = finish(api, auth, lead["id"], ticket["call_id"])
    assert response.status_code == 413 and response.json()["code"] == "call_too_large"
    assert key not in files.objects


def test_an_upload_that_took_too_long_expires(
    api, auth, lead, files, on, settings_override, db_session: Session
) -> None:
    ticket = start(api, auth, lead["id"]).json()
    assert files.browser_upload(ticket["fields"]["key"], MP3)
    row = db_session.scalars(
        select(CallRecording).where(CallRecording.id == uuid.UUID(ticket["call_id"]))
    ).one()
    bind_tenant(db_session, row.tenant_id)
    db_session.execute(
        text("UPDATE call_recordings SET created_at = :t WHERE id = :i"),
        {"t": datetime.now(UTC) - timedelta(hours=10), "i": row.id},
    )
    settings_override(calls_upload_finish_minutes=60)
    late = finish(api, auth, lead["id"], ticket["call_id"])
    assert late.status_code == 410 and late.json()["code"] == "call_upload_expired"
    assert ticket["fields"]["key"] not in files.objects


def test_only_the_person_who_started_it_can_finish_it(api, auth, lead, files, on) -> None:
    ticket = start(api, auth, lead["id"]).json()
    assert files.browser_upload(ticket["fields"]["key"], MP3)
    assert finish(api, auth, lead["id"], ticket["call_id"], "alpha.manager").status_code == 404
    assert finish(api, auth, lead["id"], ticket["call_id"]).status_code == 200


def test_an_upload_cannot_be_finished_through_another_lead(api, auth, lead, files, on) -> None:
    other = create(api, auth, AGENT, last_name="Other")
    ticket = start(api, auth, lead["id"]).json()
    assert files.browser_upload(ticket["fields"]["key"], MP3)
    assert finish(api, auth, other["id"], ticket["call_id"]).status_code == 404


# --- limits -------------------------------------------------------------------------------------


def test_a_person_may_start_only_so_many_uploads_an_hour(
    api, auth, lead, files, on, settings_override
) -> None:
    settings_override(calls_uploads_per_user_hour=2)
    assert start(api, auth, lead["id"]).status_code == 201
    assert start(api, auth, lead["id"]).status_code == 201
    third = start(api, auth, lead["id"])
    assert third.status_code == 429 and third.json()["code"] == "call_limit_reached"
    # another person has their own allowance
    assert start(api, auth, lead["id"], "alpha.manager").status_code == 201


def test_an_organisation_may_start_only_so_many_uploads_a_day(
    api, auth, lead, files, on, settings_override
) -> None:
    settings_override(calls_uploads_per_tenant_day=2)
    assert start(api, auth, lead["id"]).status_code == 201
    assert start(api, auth, lead["id"], "alpha.manager").status_code == 201
    assert start(api, auth, lead["id"], "alpha.admin").status_code == 429


# --- listening and deleting the audio -----------------------------------------------------------


def test_listening_gives_a_short_link_and_is_audited(
    api, auth, lead, files, on, db_session: Session
) -> None:
    done = upload(api, auth, files, lead["id"])
    link = api.get(calls(lead["id"], f"/{done['id']}/listen"), headers=auth(AGENT))
    assert link.status_code == 200, link.text
    body = link.json()
    assert body["expires_in_seconds"] == 60 and body["which"] == "original"
    assert body["url"].startswith("memory://files/") and "/calls/" in body["url"]
    listened = [
        r
        for r in db_session.scalars(select(AuditLog).where(AuditLog.action == "call.listened"))
        if r.entity_id == uuid.UUID(done["id"])
    ]
    assert len(listened) == 1 and listened[0].changes == {"lead_id": lead["id"], "copy": "original"}


def test_a_recording_that_never_finished_cannot_be_listened_to(api, auth, lead, files, on) -> None:
    ticket = start(api, auth, lead["id"]).json()
    response = api.get(calls(lead["id"], f"/{ticket['call_id']}/listen"), headers=auth(AGENT))
    assert response.status_code == 409 and response.json()["code"] == "call_not_ready"


def test_the_audio_can_be_deleted_and_then_it_is_gone(
    api, auth, lead, files, on, db_session: Session
) -> None:
    done = upload(api, auth, files, lead["id"])
    gone = api.delete(calls(lead["id"], f"/{done['id']}/audio"), headers=auth(AGENT))
    assert gone.status_code == 200, gone.text
    assert gone.json()["audio_available"] is False and gone.json()["audio_deleted_at"]
    assert not [k for k in files.objects if "/calls/" in k]
    again = api.get(calls(lead["id"], f"/{done['id']}/listen"), headers=auth(AGENT))
    assert again.status_code == 410 and again.json()["code"] == "call_audio_deleted"
    twice = api.delete(calls(lead["id"], f"/{done['id']}/audio"), headers=auth(AGENT))
    assert twice.status_code == 200 and twice.json()["audio_available"] is False
    removed = [
        r
        for r in db_session.scalars(select(AuditLog).where(AuditLog.action == "call.audio_deleted"))
        if r.entity_id == uuid.UUID(done["id"])
    ]
    assert len(removed) == 1


# --- who may do what ----------------------------------------------------------------------------


@pytest.mark.parametrize("user", ["alpha.support", "alpha.customer"])
def test_roles_without_lead_access_are_refused(api, auth, lead, files, on, user) -> None:
    assert api.get(calls(lead["id"]), headers=auth(user)).status_code == 403
    assert start(api, auth, lead["id"], user).status_code == 403


def test_no_token_means_401(api, lead) -> None:
    assert api.get(calls(lead["id"])).status_code == 401


def test_a_colleague_cannot_touch_my_leads_recordings_but_a_manager_can_read_them(
    api, auth, lead, files, on
) -> None:
    done = upload(api, auth, files, lead["id"])
    cid = done["id"]
    for response in (
        api.get(calls(lead["id"]), headers=auth("alpha.agent2")),
        api.get(calls(lead["id"], f"/{cid}"), headers=auth("alpha.agent2")),
        api.get(calls(lead["id"], f"/{cid}/listen"), headers=auth("alpha.agent2")),
        api.delete(calls(lead["id"], f"/{cid}/audio"), headers=auth("alpha.agent2")),
        start(api, auth, lead["id"], "alpha.agent2"),
    ):
        assert response.status_code == 404, response.text
    for user in ("alpha.manager", "alpha.admin"):
        assert api.get(calls(lead["id"], f"/{cid}"), headers=auth(user)).status_code == 200
        assert api.get(calls(lead["id"], f"/{cid}/listen"), headers=auth(user)).status_code == 200


def test_another_organisation_gets_404_for_every_call(api, auth, lead, files, on) -> None:
    done = upload(api, auth, files, lead["id"])
    for user in ("beta.admin", "beta.agent"):
        assert api.get(calls(lead["id"]), headers=auth(user)).status_code == 404
        assert api.get(calls(lead["id"], f"/{done['id']}"), headers=auth(user)).status_code == 404
        assert start(api, auth, lead["id"], user).status_code == 404


def test_made_up_and_malformed_ids(api, auth, lead, files, on) -> None:
    ghost = str(uuid.uuid4())
    assert api.get(calls(ghost), headers=auth(AGENT)).status_code == 404
    assert start(api, auth, ghost).status_code == 404
    assert api.get(calls(lead["id"], f"/{ghost}"), headers=auth(AGENT)).status_code == 404
    assert api.get(calls("not-a-uuid"), headers=auth(AGENT)).status_code == 422
    assert api.get(calls(lead["id"], "/not-a-uuid"), headers=auth(AGENT)).status_code == 422


# --- the database itself ------------------------------------------------------------------------

INSERT = text(
    "INSERT INTO call_recordings (tenant_id, lead_id, added_by_user_id, language,"
    " consent_confirmed_at,"
    " file_name, content_type, declared_size, status, failure_code, original_key)"
    " VALUES (:t, :l, :u, :language, :consent, 'a.mp3', 'audio/mpeg', 10, :status,"
    " :failure, :original)"
)
GOOD = {
    "language": "hi",
    "consent": datetime(2026, 11, 12, tzinfo=UTC),
    "status": "uploading",
    "failure": None,
    "original": None,
}
BAD_ROWS = [
    {**GOOD, "language": "fr"},  # a language outside the list
    {**GOOD, "status": "weird"},  # a status outside the list
    {**GOOD, "consent": None},  # no consent recorded
    {**GOOD, "status": "failed", "failure": None},  # failed without a reason
    {**GOOD, "status": "ready", "failure": "not_audio"},  # a reason without a failure
    {**GOOD, "status": "queued", "original": None},  # queued without the stored file
]


def test_the_database_refuses_bad_rows_and_the_application_cannot_delete(
    api, auth, lead, files, on, db_session: Session
) -> None:
    done = upload(api, auth, files, lead["id"])
    row = db_session.scalars(
        select(CallRecording).where(CallRecording.id == uuid.UUID(done["id"]))
    ).one()
    base = {"t": row.tenant_id, "l": row.lead_id, "u": row.added_by_user_id}
    for values in BAD_ROWS:
        db_session.rollback()
        bind_tenant(db_session, row.tenant_id)
        with pytest.raises(DBAPIError):
            db_session.execute(INSERT, {**base, **values})
    db_session.rollback()
    bind_tenant(db_session, row.tenant_id)
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM call_recordings"))


# --- stale uploads ------------------------------------------------------------------------------


def test_uploads_that_never_finished_expire_and_their_files_are_removed(
    api, auth, lead, files, on, db_session: Session
) -> None:
    old = start(api, auth, lead["id"]).json()
    fresh = start(api, auth, lead["id"]).json()
    assert files.browser_upload(old["fields"]["key"], MP3)
    row = db_session.scalars(
        select(CallRecording).where(CallRecording.id == uuid.UUID(old["call_id"]))
    ).one()
    bind_tenant(db_session, row.tenant_id)
    db_session.execute(
        text("UPDATE call_recordings SET created_at = :t WHERE id = :i"),
        {"t": datetime.now(UTC) - timedelta(days=3), "i": row.id},
    )
    count = service.expire_stale(db_session, files, datetime.now(UTC), tenant_id=row.tenant_id)
    assert count == 1
    assert old["fields"]["key"] not in files.objects
    states = {
        c["id"]: c["status"]
        for c in api.get(calls(lead["id"]), headers=auth(AGENT)).json()["items"]
    }
    assert states[old["call_id"]] == "expired" and states[fresh["call_id"]] == "uploading"
