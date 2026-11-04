# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The "Website chat" report, first half (docs/pilot-report.md, step PR2a).

Two sections for sales managers and administrators, each computed by the module that owns the data:
the chat funnel (public_chat: conversations, leads, share, time from the first message to the lead)
and the quality of the web leads (leads: with details, time to the first call). Aggregates only.
"""

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.modules.leads import api as leads_api
from app.modules.leads.models import Lead, LeadActivity
from app.modules.public_chat import repository
from app.modules.public_chat.models import PublicChatMessage, PublicChatSession
from tests.db.conftest import bind_principal, setup_lead_context
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world  # noqa: F401

URL = "/api/v1/reports/chat"
START = date(2026, 11, 10)
END = date(2026, 11, 16)
INSIDE = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
OUTSIDE = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)
PARAMS = {"start": START.isoformat(), "end": END.isoformat()}


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.admin"].tenant_id


def beta(world: World) -> uuid.UUID:
    return world.users["beta.admin"].tenant_id


def fake_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def web_lead(
    db: Session,
    world: World,
    *,
    last_name: str,
    created: datetime = INSIDE,
    owner: str = "alpha.agent1",
    tenant: uuid.UUID | None = None,
    source: str = "web",
    **fields: Any,
) -> Lead:
    tenant_id = tenant or alpha(world)
    owner_id = world.users[owner].id if tenant is None else world.users["beta.agent"].id
    setup_lead_context(db, tenant_id, owner_id)
    lead = Lead(
        tenant_id=tenant_id,
        last_name=last_name,
        source=source,
        owner_id=owner_id,
        created_at=created,
        **fields,
    )
    db.add(lead)
    db.flush()
    return lead


def chat_for(
    db: Session,
    world: World,
    lead: Lead | None,
    *,
    first_message: datetime,
    tenant: uuid.UUID | None = None,
) -> PublicChatSession:
    tenant_id = tenant or alpha(world)
    bind_tenant(db, tenant_id)
    seed = str(uuid.uuid4())
    row = PublicChatSession(
        tenant_id=tenant_id,
        token_hash=fake_hash("t" + seed),
        visitor_ip_hash=fake_hash("i" + seed),
        lead_id=lead.id if lead else None,
        created_at=first_message,
    )
    db.add(row)
    db.flush()
    db.add(
        PublicChatMessage(
            tenant_id=tenant_id,
            session_id=row.id,
            role="visitor",
            content="Hello",
            created_at=first_message,
        )
    )
    db.flush()
    return row


def log_call(db: Session, world: World, lead: Lead, when: datetime) -> None:
    setup_lead_context(db, lead.tenant_id, scope="all")
    db.add(
        LeadActivity(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            kind="call",
            subject="Called",
            occurred_at=when,
        )
    )
    db.flush()


def change_status(db: Session, lead: Lead, new: str, when: datetime) -> None:
    bind_tenant(db, lead.tenant_id)
    db.add(
        AuditLog(
            tenant_id=lead.tenant_id,
            actor_subject="test-subject",
            action="lead.status_changed",
            entity_type="lead",
            entity_id=lead.id,
            changes={"status": {"old": "new", "new": new}, "reason": None},
            occurred_at=when,
        )
    )
    db.flush()


def count_days(db: Session, world: World, day: date, *, started: int, leads: int) -> None:
    bind_tenant(db, alpha(world))
    repository.count_event(db, alpha(world), day, started=started, leads=leads)
    db.flush()


def section(body: dict[str, Any], index: int) -> dict[str, Any]:
    row: dict[str, Any] = body["sections"][index]["rows"][0]
    return row


def report(api, auth, who: str = "alpha.manager", **params: str) -> dict[str, Any]:
    body: dict[str, Any] = ok(api.get(URL, params={**PARAMS, **params}, headers=auth(who)))
    return body


# --- who may open it ----------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["alpha.manager", "alpha.admin"])
def test_managers_and_administrators_open_it(api, auth, world, who: str) -> None:
    body = report(api, auth, who)
    assert body["key"] == "chat" and len(body["sections"]) == 4


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support"])
def test_sales_agents_and_support_do_not_get_an_organisation_wide_report(
    api, auth, world, who: str
) -> None:
    assert code_of(api.get(URL, params=PARAMS, headers=auth(who)))[0] == 404


def test_a_customer_is_refused(api, auth, world) -> None:
    assert api.get(URL, params=PARAMS, headers=auth("alpha.customer")).status_code == 403


def test_it_is_listed_for_managers_and_not_for_agents(api, auth, world) -> None:
    def keys(who: str) -> list[str]:
        return [r["key"] for r in ok(api.get("/api/v1/reports", headers=auth(who)))["reports"]]

    assert "chat" in keys("alpha.manager") and "chat" in keys("alpha.admin")
    assert "chat" not in keys("alpha.agent1") and "chat" not in keys("alpha.support")


def test_without_a_token_it_is_401(api, world) -> None:
    assert api.get(URL, params=PARAMS).status_code == 401


# --- the funnel ---------------------------------------------------------------------------------


def test_the_funnel_adds_only_the_days_of_the_period(api, auth, world, db_session) -> None:
    count_days(db_session, world, date(2026, 11, 9), started=100, leads=50)  # the day before
    count_days(db_session, world, date(2026, 11, 10), started=6, leads=2)  # first day: counted
    count_days(db_session, world, date(2026, 11, 16), started=4, leads=2)  # last day: counted
    count_days(db_session, world, date(2026, 11, 17), started=100, leads=50)  # the day after
    row = section(report(api, auth), 0)
    assert (row["started"], row["leads"]) == (10, 4)
    assert row["lead_share"] == "40.0"


def test_an_empty_period_has_no_share_and_no_times(api, auth, world) -> None:
    row = section(report(api, auth), 0)
    assert (row["started"], row["leads"]) == (0, 0)
    assert row["lead_share"] is None and row["median_seconds_to_lead"] is None


def test_the_time_from_the_first_message_to_the_lead(api, auth, world, db_session) -> None:
    for seconds, name in ((60, "A"), (120, "B"), (600, "C")):
        lead = web_lead(
            db_session, world, last_name=name, created=INSIDE + timedelta(seconds=seconds)
        )
        chat_for(db_session, world, lead, first_message=INSIDE)
    chat_for(db_session, world, None, first_message=INSIDE)  # a chat that never gave a lead
    row = section(report(api, auth), 0)
    assert row["measured"] == 3
    assert row["median_seconds_to_lead"] == 120
    assert row["p90_seconds_to_lead"] == 600


def test_a_lead_made_outside_the_period_is_not_measured(api, auth, world, db_session) -> None:
    lead = web_lead(db_session, world, last_name="Late", created=OUTSIDE)
    chat_for(db_session, world, lead, first_message=OUTSIDE - timedelta(seconds=30))
    assert section(report(api, auth), 0)["measured"] == 0


def test_another_organisations_chats_never_count(api, auth, world, db_session) -> None:
    other = web_lead(db_session, world, last_name="Beta", tenant=beta(world))
    chat_for(
        db_session, world, other, first_message=INSIDE - timedelta(seconds=5), tenant=beta(world)
    )
    row = section(report(api, auth), 0)
    assert row["measured"] == 0 and row["started"] == 0


# --- the quality of the web leads ---------------------------------------------------------------

FULL: dict[str, Any] = {
    "budget_min_inr": 8_000_000,
    "budget_max_inr": 12_000_000,
    "location": "Kokapet",
    "property_type": "apartment",
}


def test_only_web_leads_of_the_period_are_counted_and_details_are_checked(
    api, auth, world, db_session
) -> None:
    web_lead(db_session, world, last_name="Full", **FULL)
    web_lead(db_session, world, last_name="NoArea", **{**FULL, "location": None})
    web_lead(db_session, world, last_name="BlankArea", **{**FULL, "location": "   "})
    web_lead(db_session, world, last_name="OnlyMax", **{**FULL, "budget_min_inr": None})
    web_lead(
        db_session,
        world,
        last_name="NoBudget",
        **{**FULL, "budget_min_inr": None, "budget_max_inr": None},
    )
    web_lead(db_session, world, last_name="NoType", **{**FULL, "property_type": None})
    web_lead(db_session, world, last_name="Phone", source="phone", **FULL)  # not a web lead
    web_lead(db_session, world, last_name="Old", created=OUTSIDE, **FULL)  # outside the period
    row = section(report(api, auth), 1)
    assert row["web_leads"] == 6
    assert row["with_details"] == 2  # Full and OnlyMax (a budget range may have one end)
    assert row["with_details_share"] == "33.3"


def test_the_first_call_is_the_earlier_of_a_logged_call_and_the_change_to_contacted(
    api, auth, world, db_session
) -> None:
    hour = timedelta(hours=1)
    one = web_lead(db_session, world, last_name="CallOnly", **FULL)
    log_call(db_session, world, one, INSIDE + 2 * hour)
    two = web_lead(db_session, world, last_name="StatusOnly", **FULL)
    change_status(db_session, two, "contacted", INSIDE + 4 * hour)
    three = web_lead(db_session, world, last_name="Both", **FULL)
    log_call(db_session, world, three, INSIDE + 6 * hour)
    change_status(db_session, three, "contacted", INSIDE + 1 * hour)
    web_lead(db_session, world, last_name="Nobody", **FULL)
    row = section(report(api, auth), 1)
    assert row["web_leads"] == 4 and row["called"] == 3
    assert row["median_hours_to_first_call"] == "2.0"  # 2h, 4h and 1h


def test_other_status_changes_and_other_activities_are_not_a_first_call(
    api, auth, world, db_session
) -> None:
    lead = web_lead(db_session, world, last_name="Quiet", **FULL)
    change_status(db_session, lead, "qualified", INSIDE + timedelta(hours=1))
    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.add(
        LeadActivity(
            tenant_id=alpha(world), lead_id=lead.id, kind="note", subject="n", occurred_at=INSIDE
        )
    )
    db_session.flush()
    row = section(report(api, auth), 1)
    assert row["called"] == 0 and row["median_hours_to_first_call"] is None


def test_a_call_logged_before_the_lead_existed_counts_as_no_wait(
    api, auth, world, db_session
) -> None:
    lead = web_lead(db_session, world, last_name="Backdated", **FULL)
    log_call(db_session, world, lead, INSIDE - timedelta(hours=3))
    assert section(report(api, auth), 1)["median_hours_to_first_call"] == "0.0"


def test_managers_see_every_agents_web_leads(api, auth, world, db_session) -> None:
    web_lead(db_session, world, last_name="Mine", owner="alpha.agent1", **FULL)
    web_lead(db_session, world, last_name="Theirs", owner="alpha.agent2", **FULL)
    assert section(report(api, auth), 1)["web_leads"] == 2


def test_another_organisations_leads_never_count(api, auth, world, db_session) -> None:
    web_lead(db_session, world, last_name="Beta", tenant=beta(world), **FULL)
    assert section(report(api, auth), 1)["web_leads"] == 0


# --- the page, the file and what must never be in them ------------------------------------------


def test_the_report_and_its_file_hold_aggregates_only(api, auth, world, db_session) -> None:
    lead = web_lead(db_session, world, last_name="Zyxwvu", phone="+91 98765 43210", **FULL)
    conversation = chat_for(db_session, world, lead, first_message=INSIDE - timedelta(seconds=40))
    log_call(db_session, world, lead, INSIDE + timedelta(hours=1))
    shown = api.get(URL, params=PARAMS, headers=auth("alpha.manager")).text
    csv = api.get(f"{URL}/csv", params=PARAMS, headers=auth("alpha.manager")).text
    secrets = ("Zyxwvu", "98765", "Kokapet", str(lead.id), str(conversation.id))
    for text in (shown, csv):
        for secret in (*secrets, conversation.token_hash[:16], conversation.visitor_ip_hash[:16]):
            assert secret not in text, secret


def test_the_csv_has_both_sections(api, auth, world) -> None:
    response = api.get(f"{URL}/csv", params=PARAMS, headers=auth("alpha.manager"))
    assert response.status_code == 200 and "text/csv" in response.headers["content-type"]
    text = response.text
    assert "Website chat" in text and "Web leads" in text


def test_a_bad_period_is_refused(api, auth, world) -> None:
    bad = api.get(
        URL, params={"start": "2026-11-16", "end": "2026-11-10"}, headers=auth("alpha.manager")
    )
    assert code_of(bad)[0] == 422


# --- record-level access of the building block -------------------------------------------------


def test_created_at_of_gives_a_person_only_the_leads_they_may_read(db_session, world) -> None:
    mine = web_lead(db_session, world, last_name="Mine", owner="alpha.agent1")
    theirs = web_lead(db_session, world, last_name="Theirs", owner="alpha.agent2")

    def seen_by(who: str) -> set[uuid.UUID]:
        principal = principal_for(world.users[who], ROLES[who])
        bind_principal(db_session, principal)
        return set(leads_api.created_at_of(db_session, principal, [mine.id, theirs.id]))

    assert seen_by("alpha.agent1") == {mine.id}
    assert seen_by("alpha.agent2") == {theirs.id}
    assert seen_by("alpha.manager") == {mine.id, theirs.id}
    assert (
        leads_api.created_at_of(
            db_session, principal_for(world.users["alpha.admin"], ROLES["alpha.admin"]), []
        )
        == {}
    )
