# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Call notes through the real API (ADR 0035, CN3): the organisation's choice of frame, asking for a
draft on a call, reading the drafts back. Real application, database, agent registry and
authorization; only the model is a scripted one that the test puts on the app."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ModelReply, ToolUse
from app.modules.call_notes.models import CallNote
from app.modules.calls.models import CallRecording
from app.modules.leads.models import Lead
from tests.db.test_approvals import alpha
from tests.db.test_call_notes_run import BUDGET, NEED, SEGMENTS, TIMELINE, Metered, answer
from tests.db.test_custom_agents_service import AI
from tests.db.test_qualifier_assess import ScriptedModel, lead_with_details
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world

SETTINGS = "/api/v1/call-notes/settings"


def says(arguments: dict[str, Any] | None = None) -> Metered:
    return Metered(ToolUse("t1", "submit_notes", arguments or answer(BUDGET, TIMELINE, NEED)))


def use(api: Any, model: Any) -> Any:
    api.app.state.call_notes_model = model
    return model


def notes_url(lead: Lead, call: CallRecording) -> str:
    return f"/api/v1/leads/{lead.id}/calls/{call.id}/notes"


@pytest.fixture
def lead(db_session: Session, world: World) -> Lead:
    return lead_with_details(db_session, world)


@pytest.fixture
def call(db_session: Session, world: World, lead: Lead) -> CallRecording:
    bind_tenant(db_session, alpha(world))
    row = CallRecording(
        tenant_id=alpha(world),
        lead_id=lead.id,
        added_by_user_id=world.users["alpha.agent1"].id,
        language="en",
        consent_confirmed_at=datetime.now(UTC),
        file_name="call.mp3",
        content_type="audio/mpeg",
        declared_size=10,
        status="ready",
        original_key="calls/original.mp3",
        transcript_text=" ".join(s["text"] for s in SEGMENTS),
        transcript_segments=SEGMENTS,
    )
    db_session.add(row)
    db_session.flush()
    return row


def switch_on(api: Any, auth: Headers) -> None:
    ok(api.patch("/api/v1/agents/call_notes", json={"enabled": True}, headers=auth("alpha.admin")))


@pytest.fixture
def live(api: Any, auth: Headers) -> Any:
    switch_on(api, auth)
    return use(api, says())


def ask(api: Any, auth: Headers, lead: Lead, call: CallRecording, who: str = "alpha.agent1") -> Any:
    return api.post(notes_url(lead, call), headers=auth(who))


# --- the organisation's frame -------------------------------------------------------------------


@pytest.mark.parametrize("who", ["alpha.admin", "alpha.manager", "alpha.agent1"])
def test_everyone_who_may_ask_for_notes_can_read_the_settings(api, auth, who) -> None:
    body = ok(api.get(SETTINGS, headers=auth(who)))
    assert (body["framework"], body["version"]) == ("bant", 0)
    frames = {f["key"]: [x["key"] for x in f["fields"]] for f in body["frameworks"]}
    assert frames == {
        "bant": ["budget", "authority", "need", "timeline"],
        "meddic": [
            "metrics",
            "economic_buyer",
            "decision_criteria",
            "decision_process",
            "identify_pain",
            "champion",
        ],
    }
    assert all(f["label"] and f["hint"] for fr in body["frameworks"] for f in fr["fields"])


def test_support_customers_and_strangers_cannot_read_the_settings(api, auth) -> None:
    assert api.get(SETTINGS, headers=auth("alpha.support")).status_code == 403
    assert api.get(SETTINGS, headers=auth("alpha.customer")).status_code == 403
    assert api.get(SETTINGS).status_code == 401


def test_an_administrator_chooses_the_frame_and_it_is_audited(api, auth, db_session, world) -> None:
    body = ok(api.put(SETTINGS, json={"framework": "meddic"}, headers=auth("alpha.admin")))
    assert (body["framework"], body["version"]) == ("meddic", 1)
    assert ok(api.get(SETTINGS, headers=auth("alpha.agent1")))["framework"] == "meddic"
    bind_tenant(db_session, alpha(world))
    [entry] = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "call_notes.framework_changed")
    )
    assert entry.changes == {"from": "bant", "to": "meddic"}


@pytest.mark.parametrize(
    "who", ["alpha.manager", "alpha.agent1", "alpha.support", "alpha.customer"]
)
def test_only_administrators_change_the_frame(api, auth, who) -> None:
    response = api.put(SETTINGS, json={"framework": "meddic"}, headers=auth(who))
    assert response.status_code == 403
    assert ok(api.get(SETTINGS, headers=auth("alpha.admin")))["framework"] == "bant"


def test_a_stale_screen_cannot_overwrite_a_newer_choice(api, auth) -> None:
    admin = auth("alpha.admin")
    ok(api.put(SETTINGS, json={"framework": "meddic"}, headers=admin))
    stale = api.put(SETTINGS, json={"framework": "bant", "version": 0}, headers=admin)
    assert stale.status_code == 409
    again = ok(api.put(SETTINGS, json={"framework": "bant", "version": 1}, headers=admin))
    assert (again["framework"], again["version"]) == ("bant", 2)
    wrong = api.put(SETTINGS, json={"framework": "meddic", "version": 1}, headers=admin)
    assert wrong.status_code == 409
    first_with_version = api.put(
        SETTINGS, json={"framework": "bant", "version": 7}, headers=auth("beta.admin")
    )
    assert first_with_version.status_code == 409


def test_saving_the_same_frame_changes_nothing(api, auth, db_session, world) -> None:
    admin = auth("alpha.admin")
    ok(api.put(SETTINGS, json={"framework": "meddic"}, headers=admin))
    same = ok(api.put(SETTINGS, json={"framework": "meddic", "version": 1}, headers=admin))
    assert same["version"] == 1
    bind_tenant(db_session, alpha(world))
    changes = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "call_notes.framework_changed")
    ).all()
    assert len(changes) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"framework": "spin"},
        {"framework": ""},
        {},
        {"framework": "bant", "tenant_id": str(uuid.uuid4())},
        {"framework": "bant", "enabled": True},
        {"framework": ["bant"]},
    ],
    ids=["unknown-frame", "empty", "missing", "tenant-id", "extra-field", "list"],
)
def test_a_bad_settings_body_is_refused(api, auth, body) -> None:
    assert api.put(SETTINGS, json=body, headers=auth("alpha.admin")).status_code == 422


def test_each_organisation_has_its_own_frame(api, auth) -> None:
    ok(api.put(SETTINGS, json={"framework": "meddic"}, headers=auth("alpha.admin")))
    assert ok(api.get(SETTINGS, headers=auth("beta.admin")))["framework"] == "bant"


# --- asking for a draft -------------------------------------------------------------------------


def test_an_agent_asks_for_notes_on_their_own_leads_call(api, auth, live, lead, call) -> None:
    body = ok(ask(api, auth, lead, call), 201)
    assert (body["version_no"], body["framework"]) == (1, "bant")
    by_field = {ln["field"]: ln for ln in body["lines"]}
    assert by_field["budget"]["state"] == "stated"
    assert by_field["budget"]["quote"].startswith("My budget is around")
    assert (by_field["budget"]["start_ms"], by_field["budget"]["end_ms"]) == (6000, 14000)
    assert by_field["budget"]["label"] == "Budget"
    assert by_field["authority"]["state"] == "unknown"
    assert body["requested_by_user_id"] == str(uuid.UUID(body["requested_by_user_id"]))
    assert "tokens" not in body and "tenant_id" not in body


def test_the_response_never_carries_the_prompt_or_the_models_raw_answer(
    api, auth, live, lead, call
) -> None:
    text = ask(api, auth, lead, call).text
    for secret in ("submit_notes", "system", "Transcript lines"):
        assert secret not in text


def test_the_organisations_frame_decides_the_checklist(api, auth, live, lead, call) -> None:
    ok(api.put(SETTINGS, json={"framework": "meddic"}, headers=auth("alpha.admin")))
    use(api, says({"checklist": []}))
    body = ok(ask(api, auth, lead, call), 201)
    assert body["framework"] == "meddic"
    assert [ln["field"] for ln in body["lines"]][:2] == ["metrics", "economic_buyer"]


def test_the_client_cannot_choose_the_frame_or_anything_else(api, auth, live, lead, call) -> None:
    response = api.post(
        notes_url(lead, call),
        json={"framework": "meddic", "tenant_id": str(uuid.uuid4()), "lead_id": str(uuid.uuid4())},
        headers=auth("alpha.agent1"),
    )
    body = ok(response, 201)
    assert body["framework"] == "bant"


def test_it_is_switched_off_until_an_administrator_turns_it_on(api, auth, lead, call) -> None:
    model = use(api, says())
    response = ask(api, auth, lead, call)
    assert code_of(response) == (503, "agent_unavailable")
    assert model.calls == []


def test_a_manager_may_ask_for_notes_on_an_agents_lead(api, auth, live, lead, call) -> None:
    assert ok(ask(api, auth, lead, call, "alpha.manager"), 201)["version_no"] == 1


@pytest.mark.parametrize("who", ["alpha.agent2", "beta.agent", "beta.admin"])
def test_a_lead_one_may_not_read_is_not_found(api, auth, live, lead, call, who) -> None:
    model = live
    response = ask(api, auth, lead, call, who)
    assert response.status_code == 404
    assert model.calls == []


@pytest.mark.parametrize("who", ["alpha.support", "alpha.customer"])
def test_support_and_customers_are_refused(api, auth, live, lead, call, who) -> None:
    assert ask(api, auth, lead, call, who).status_code == 403
    assert live.calls == []


def test_unauthenticated_requests_are_refused(api, lead, call) -> None:
    assert api.post(notes_url(lead, call)).status_code == 401
    assert api.get(notes_url(lead, call)).status_code == 401


def test_made_up_and_mixed_up_ids_are_not_found(
    api, auth, live, lead, call, db_session, world
) -> None:
    other_lead = lead_with_details(db_session, world, "alpha.agent1")
    for path in (
        f"/api/v1/leads/{lead.id}/calls/{uuid.uuid4()}/notes",
        f"/api/v1/leads/{uuid.uuid4()}/calls/{call.id}/notes",
        f"/api/v1/leads/{other_lead.id}/calls/{call.id}/notes",  # a call of another lead
    ):
        assert api.post(path, headers=auth("alpha.agent1")).status_code == 404
    assert live.calls == []


def test_a_recording_without_a_transcript_is_a_conflict(
    api, auth, live, lead, call, db_session
) -> None:
    call.status, call.transcript_text, call.transcript_segments = "queued", None, []
    db_session.flush()
    assert code_of(ask(api, auth, lead, call)) == (409, "call_transcript_not_ready")


def test_a_bad_answer_is_a_422_and_stores_nothing_but_keeps_the_tokens(
    api, auth, live, lead, call, db_session, world
) -> None:
    use(api, Metered(ToolUse("t", "submit_notes", {"checklist": [], "approve": True})))
    assert code_of(ask(api, auth, lead, call)) == (422, "call_notes_bad_answer")
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(CallNote)).all() == []
    used = agents_api.effective(db_session, alpha(world), "call_notes", AI, datetime.now(UTC))
    assert used.used_tokens == 150


def test_an_answer_with_mostly_invented_quotes_is_a_422(api, auth, live, lead, call) -> None:
    bad = [
        {**BUDGET, "quote": "I will pay five crore", "value": "five crore"},
        {**NEED, "quote": "I want a villa please", "value": "a villa"},
        TIMELINE,
    ]
    use(api, says(answer(*bad)))
    assert code_of(ask(api, auth, lead, call)) == (422, "call_notes_unverified_answer")


def test_a_fourth_draft_in_a_day_is_refused(api, auth, live, lead, call) -> None:
    for _ in range(3):
        ok(ask(api, auth, lead, call), 201)
    model = use(api, says())
    assert code_of(ask(api, auth, lead, call)) == (429, "call_notes_rate_limited")
    assert model.calls == []


def test_asking_changes_no_lead_and_makes_no_proposal(
    api, auth, live, lead, call, db_session, world
) -> None:
    version = lead.version
    ok(ask(api, auth, lead, call), 201)
    db_session.refresh(lead)
    assert lead.version == version
    ok(api.get("/api/v1/approvals/actions", headers=auth("alpha.manager")))
    assert ok(api.get("/api/v1/approvals/actions", headers=auth("alpha.manager")))["items"] == []


# --- reading the drafts -------------------------------------------------------------------------


def test_before_any_draft_the_newest_is_empty(api, auth, lead, call) -> None:
    body = ok(api.get(notes_url(lead, call), headers=auth("alpha.agent1")))
    assert body == {"newest": None, "versions": []}


def test_the_newest_draft_and_the_list_of_versions(api, auth, live, lead, call) -> None:
    ok(ask(api, auth, lead, call), 201)
    ok(ask(api, auth, lead, call), 201)
    body = ok(api.get(notes_url(lead, call), headers=auth("alpha.agent1")))
    assert body["newest"]["version_no"] == 2
    assert [v["version_no"] for v in body["versions"]] == [2, 1]
    first = ok(api.get(f"{notes_url(lead, call)}/1", headers=auth("alpha.agent1")))
    assert first["version_no"] == 1 and first["lines"]


def test_a_version_that_does_not_exist_is_not_found(api, auth, live, lead, call) -> None:
    ok(ask(api, auth, lead, call), 201)
    assert api.get(f"{notes_url(lead, call)}/9", headers=auth("alpha.agent1")).status_code == 404
    assert api.get(f"{notes_url(lead, call)}/0", headers=auth("alpha.agent1")).status_code == 422


@pytest.mark.parametrize("who", ["alpha.agent2", "beta.agent", "alpha.support", "alpha.customer"])
def test_drafts_of_a_lead_one_may_not_read_stay_hidden(api, auth, live, lead, call, who) -> None:
    ok(ask(api, auth, lead, call), 201)
    assert api.get(notes_url(lead, call), headers=auth(who)).status_code in (403, 404)
    assert api.get(f"{notes_url(lead, call)}/1", headers=auth(who)).status_code in (403, 404)


def test_a_manager_reads_an_agents_drafts(api, auth, live, lead, call) -> None:
    ok(ask(api, auth, lead, call), 201)
    assert ok(api.get(notes_url(lead, call), headers=auth("alpha.manager")))["newest"]


def test_a_version_number_only_means_something_inside_its_own_call(
    api, auth, live, lead, call, db_session, world
) -> None:
    ok(ask(api, auth, lead, call), 201)
    second = CallRecording(
        tenant_id=alpha(world),
        lead_id=lead.id,
        added_by_user_id=world.users["alpha.agent1"].id,
        language="en",
        consent_confirmed_at=datetime.now(UTC),
        file_name="other.mp3",
        content_type="audio/mpeg",
        declared_size=10,
        status="ready",
        original_key="calls/other.mp3",
        transcript_text="Hello there, is this a good time to talk?",
        transcript_segments=[
            {"start": 0.0, "end": 4.0, "text": "Hello there, is this a good time"}
        ],
    )
    db_session.add(second)
    db_session.flush()
    assert api.get(f"{notes_url(lead, second)}/1", headers=auth("alpha.agent1")).status_code == 404
    assert ok(api.get(notes_url(lead, second), headers=auth("alpha.agent1"))) == {
        "newest": None,
        "versions": [],
    }
