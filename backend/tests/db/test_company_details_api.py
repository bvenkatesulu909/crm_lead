# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Company details on a lead through the real API and the real worker (BP-02, ADR 0026 EN3).

Ask -> the worker reads the company's (fictional, demo) website -> the suggestions are shown next
to the lead's values -> the person keeps some. The values saved come from the stored evidence,
never from the request. People come from test_quotes_api.py (tenant alpha: admin, manager, agent1,
agent2, support, customers; tenant beta: admin and agent).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.outbox import OutboxJob
from app.modules.leads.models import Lead
from app.modules.webcheck.models import WebEvidence
from tests.db.conftest import setup_lead_context
from tests.db.test_approvals import alpha
from tests.db.test_quotes_api import Headers, World, auth, code_of, ok, world  # noqa: F401
from tests.db.test_webcheck_api import api, make_api, settings, worker  # noqa: F401

DETAILS = "/api/v1/webcheck/company-details"
ACME = "https://acme-builders.demo.example"


def add_lead(db_session: Session, world: World, owner: str = "alpha.agent1", **fields: Any) -> Lead:
    owner_id = world.users[owner].id
    setup_lead_context(db_session, alpha(world), owner_id)
    lead = Lead(tenant_id=alpha(world), last_name="Rao", owner_id=owner_id, **fields)
    db_session.add(lead)
    db_session.flush()
    return lead


def switch(api: Any, auth: Headers, on: bool = True) -> None:
    current = ok(api.get("/api/v1/agents/company_details", headers=auth("alpha.admin")))
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    ok(api.patch("/api/v1/agents/company_details", json=body, headers=auth("alpha.admin")))


def ask(api: Any, auth: Headers, lead: Any, user: str = "alpha.agent1", **extra: Any) -> Any:
    return api.post(DETAILS, json={"lead_id": str(lead.id), **extra}, headers=auth(user))


def read(api: Any, auth: Headers, lead: Any, user: str = "alpha.agent1") -> Any:
    return api.get(DETAILS, params={"lead_id": str(lead.id)}, headers=auth(user))


def apply(api: Any, auth: Headers, lead: Any, latest: dict[str, Any], fields: list[str],
          version: int, user: str = "alpha.agent1", **extra: Any) -> Any:  # fmt: skip
    body = {"lead_id": str(lead.id), "evidence_id": latest["id"], "fields": fields,
            "version": version, **extra}  # fmt: skip
    return api.post(f"{DETAILS}/apply", json=body, headers=auth(user))


def looked_up(api, auth, worker, lead, user: str = "alpha.agent1") -> dict[str, Any]:
    ok(ask(api, auth, lead, user), 202)
    worker()
    body: dict[str, Any] = ok(read(api, auth, lead, user))
    return body


# --- asking -------------------------------------------------------------------------------------


def test_it_is_off_until_an_administrator_switches_it_on(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world, company_website=ACME)
    assert code_of(ask(api, auth, lead)) == (503, "company_details_unavailable")
    switch(api, auth)
    assert ok(ask(api, auth, lead), 202)["status"] == "checking"


def test_the_platform_switch_stops_it(make_api, auth, world, db_session) -> None:
    api = make_api(webcheck_disabled=True)
    lead = add_lead(db_session, world, company_website=ACME)
    assert ask(api, auth, lead).status_code == 503


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({}, "company_host_no_source"),
        ({"email": "jamie@gmail.com"}, "company_host_free_mail"),
        ({"company_website": "https://printer.local"}, "company_host_internal_name"),
        ({"company_website": "https://api.crmlead.co.in"}, "company_host_denied"),
    ],
)
def test_a_lead_without_a_usable_company_site_is_told_why(
    api, auth, world, db_session, fields, code
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, **fields)
    assert code_of(ask(api, auth, lead)) == (422, code)


def test_the_host_is_never_taken_from_the_request(api, auth, world, db_session) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    for extra in ({"host": "169.254.169.254"}, {"url": "https://evil.example"},
                  {"tenant_id": str(uuid.uuid4())}):  # fmt: skip
        assert ask(api, auth, lead, **extra).status_code == 422
    ok(ask(api, auth, lead), 202)
    jobs = db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "webcheck.company_details"))
    assert [job.payload["host"] for job in jobs] == ["acme-builders.demo.example"]


def test_the_work_email_domain_is_used_when_there_is_no_website(
    api, auth, world, db_session
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, email="jamie@Acme-Builders.demo.example")
    ok(ask(api, auth, lead), 202)
    [job] = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "webcheck.company_details")
    )
    assert job.payload["host"] == "acme-builders.demo.example"
    assert "jamie" not in str(job.payload)  # nothing about the person goes into the job


@pytest.mark.parametrize(
    ("user", "expected"),
    [("alpha.agent2", 404), ("beta.admin", 404), ("alpha.support", 404), ("alpha.customer1", 403)],
)
def test_only_people_who_may_read_the_lead_can_ask(
    api, auth, world, db_session, user, expected
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    assert ask(api, auth, lead, user).status_code == expected
    assert read(api, auth, lead, user).status_code == expected


def test_a_made_up_lead_is_not_found(api, auth, world) -> None:
    switch(api, auth)
    assert ask(api, auth, type("X", (), {"id": uuid.uuid4()})).status_code == 404


def test_one_person_has_an_hourly_limit(make_api, auth, world, db_session) -> None:
    api = make_api(company_details_per_user_hour=1)
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    ok(ask(api, auth, lead), 202)
    assert code_of(ask(api, auth, lead)) == (429, "company_details_limit_reached")


# --- looking up and reading ---------------------------------------------------------------------


def test_the_suggestions_appear_next_to_the_current_values(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, email="jamie@acme-builders.demo.example")
    body = looked_up(api, auth, worker, lead)
    assert body["current"] == {
        "company_website": None,
        "company_industry": None,
        "company_size": None,
        "version": 1,
    }
    latest = body["latest"]
    assert (latest["verdict"], latest["company_website"], latest["company_industry"],
            latest["company_size"], latest["name"]) == (
        "found", ACME, "real_estate", "11-50", "Acme Builders",
    )  # fmt: skip
    assert latest["pages"] == [f"{ACME}/", f"{ACME}/about"]
    # Running the job again changes nothing (safe to run twice).
    assert worker() == 0


def test_a_poisoned_site_is_kept_clean(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://poisoned.demo.example")
    latest = looked_up(api, auth, worker, lead)["latest"]
    assert "evil.example" not in (latest["name"] or "") + latest["excerpt"]
    assert {"link", "instruction_phrase"} <= set(latest["cleaned"])


def test_a_site_inside_a_network_is_refused_and_recorded(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://intranet.demo.example")
    latest = looked_up(api, auth, worker, lead)["latest"]
    assert (latest["verdict"], latest["error_code"], latest["company_website"]) == (
        "error",
        "private_address",
        None,
    )


def test_company_lookups_stay_out_of_the_registry_check_list(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    looked_up(api, auth, worker, lead)
    listed = ok(api.get("/api/v1/webcheck/evidence",
                        params={"target_type": "lead", "target_id": str(lead.id)},
                        headers=auth("alpha.agent1")))  # fmt: skip
    assert listed["items"] == []


# --- applying -----------------------------------------------------------------------------------


def test_chosen_suggestions_are_saved_from_the_evidence(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    body = looked_up(api, auth, worker, lead)
    saved = ok(apply(api, auth, lead, body["latest"], ["company_industry", "company_size"],
                     body["current"]["version"]))  # fmt: skip
    assert saved["current"]["company_industry"] == "real_estate"
    assert saved["current"]["company_size"] == "11-50"
    setup_lead_context(db_session, alpha(world), scope="all")
    actions = [a.action for a in db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == lead.id).order_by(AuditLog.seq))]  # fmt: skip
    assert actions[-2:] == ["lead.updated", "lead.enriched"]
    [enriched] = db_session.scalars(select(AuditLog).where(AuditLog.action == "lead.enriched"))
    assert enriched.changes == {
        "fields": ["company_industry", "company_size"],
        "source": "company_site",
        "evidence_id": body["latest"]["id"],
    }


def test_values_cannot_be_sent_with_the_request(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    body = looked_up(api, auth, worker, lead)
    response = apply(api, auth, lead, body["latest"], ["company_size"], 1,
                     company_size="1001+")  # fmt: skip
    assert response.status_code == 422


@pytest.mark.parametrize("fields", [[], ["company_name"], ["company_size", "company_size"]])
def test_only_known_fields_once_each(api, auth, world, db_session, worker, fields) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    body = looked_up(api, auth, worker, lead)
    assert apply(api, auth, lead, body["latest"], fields, 1).status_code == 422


def test_a_field_without_a_suggestion_cannot_be_saved(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://plain.demo.example")
    body = looked_up(api, auth, worker, lead)
    assert body["latest"]["company_size"] is None
    assert code_of(apply(api, auth, lead, body["latest"], ["company_size"], 1)) == (
        422,
        "field_not_suggested",
    )


def test_evidence_of_another_lead_cannot_be_used(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    first = add_lead(db_session, world, company_website=ACME)
    other = add_lead(db_session, world, company_website="https://plain.demo.example")
    body = looked_up(api, auth, worker, first)
    assert apply(api, auth, other, body["latest"], ["company_industry"], 1).status_code == 404


def test_a_stale_version_is_refused(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    body = looked_up(api, auth, worker, lead)
    assert apply(api, auth, lead, body["latest"], ["company_size"], 7).status_code == 409


@pytest.mark.parametrize("user", ["alpha.agent2", "beta.admin"])
def test_nobody_else_can_save_them(api, auth, world, db_session, worker, user) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    body = looked_up(api, auth, worker, lead)
    assert apply(api, auth, lead, body["latest"], ["company_size"], 1, user).status_code == 404


def test_the_evidence_itself_cannot_be_changed(world, db_session, api, auth, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website=ACME)
    looked_up(api, auth, worker, lead)
    setup_lead_context(db_session, alpha(world), scope="all")
    row = db_session.scalar(select(WebEvidence).where(WebEvidence.target_id == lead.id))
    assert row is not None
    row.suggestions = {"size": "1001+"}
    with pytest.raises(Exception, match="(?i)(insert-only|permission|not allowed|refus)"):
        db_session.flush()
