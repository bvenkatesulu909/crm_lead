# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The "Follow-ups" report (ADR 0036, step FM7): what happened to the drafts the CRM made, per
rule, and how often the lead wrote back within two weeks of an approved follow-up.

Aggregates only, for sales managers and administrators. Drafts are inserted in known states so the
numbers can be checked exactly; people come from test_quotes_api.py.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.approvals.models import AgentAction
from app.modules.communications.models import EmailMessage
from app.modules.leads.models import Lead
from tests.db.conftest import setup_lead_context
from tests.db.test_quotes_api import World, api, auth, code_of, ok, world  # noqa: F401

URL = "/api/v1/reports/follow_ups"
START = date(2026, 11, 10)
END = date(2026, 11, 16)
INSIDE = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
OUTSIDE = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)
PARAMS = {"start": START.isoformat(), "end": END.isoformat()}
PRIVATE_SUBJECT = "Zyxwvu private subject"
PRIVATE_BODY = "Plot 42 near Kokapet, call 98765 43210"


def tenant(world: World, name: str = "alpha") -> uuid.UUID:
    return world.users[f"{name}.admin"].tenant_id


def lead(db: Session, world: World, last_name: str = "Qwertyu", org: str = "alpha") -> Lead:
    owner = world.users["alpha.agent1" if org == "alpha" else "beta.agent"].id
    setup_lead_context(db, tenant(world, org), owner)
    row = Lead(tenant_id=tenant(world, org), last_name=last_name, owner_id=owner)
    db.add(row)
    db.flush()
    return row


def draft(
    db: Session,
    world: World,
    target: Lead,
    status: str = "pending",
    *,
    created: datetime = INSIDE,
    decided_after: timedelta = timedelta(minutes=30),
    edited: bool = False,
    org: str = "alpha",
    rule: str = "task_due_today",
    agent: str = "follow_up",
) -> AgentAction:
    """A follow-up draft as the scan would store it, in a chosen state."""
    asker = world.users[f"{org}.admin"].id
    decider = world.users["alpha.manager" if org == "alpha" else "beta.agent"].id
    bind_tenant(db, tenant(world, org))
    verification: dict[str, Any] = {"warnings": []}
    if edited:
        verification["edited"] = {"fields": ["body"], "by": str(decider)}
    final = status != "pending"
    action = AgentAction(
        id=uuid.uuid4(),
        tenant_id=tenant(world, org),
        kind="communication.send_follow_up",
        target_type="lead",
        target_id=target.id,
        payload={"reason_code": rule, "subject": PRIVATE_SUBJECT, "body": PRIVATE_BODY},
        verification=verification,
        reason="A follow-up task for this lead is due today.",
        agent=agent,
        requested_by_user_id=asker,
        status=status,
        expires_at=created + timedelta(days=7),
        created_at=created,
        decided_by_user_id=decider if final and status != "expired" else None,
        decided_at=created + decided_after if final else None,
        decision_note="Not the right moment." if status == "rejected" else None,
    )
    db.add(action)
    db.flush()
    return action


def reply(db: Session, world: World, target: Lead, at: datetime, org: str = "alpha") -> None:
    bind_tenant(db, tenant(world, org))
    db.add(
        EmailMessage(
            tenant_id=tenant(world, org),
            direction="inbound_logged",
            status="logged",
            lead_id=target.id,
            to_address="team@example.test",
            subject="Re: hello",
            body="Yes, Saturday works.",
            sent_by_user_id=world.users["alpha.agent1" if org == "alpha" else "beta.agent"].id,
            created_at=at,
        )
    )
    db.flush()


def report(api, auth, who: str = "alpha.manager") -> dict[str, Any]:
    body: dict[str, Any] = ok(api.get(URL, params=PARAMS, headers=auth(who)))
    assert body["key"] == "follow_ups"
    return body


def rows(body: dict[str, Any], index: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = body["sections"][index]["rows"]
    return found


# --- who may open it ----------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["alpha.manager", "alpha.admin"])
def test_managers_and_administrators_open_it(api, auth, world, who: str) -> None:
    assert len(report(api, auth, who)["sections"]) == 2


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support"])
def test_agents_and_support_do_not_get_it(api, auth, world, who: str) -> None:
    assert code_of(api.get(URL, params=PARAMS, headers=auth(who)))[0] == 404


def test_a_customer_is_refused_and_no_token_is_401(api, auth, world) -> None:
    assert api.get(URL, params=PARAMS, headers=auth("alpha.customer")).status_code == 403
    assert api.get(URL, params=PARAMS).status_code == 401


def test_it_is_listed_for_managers_only(api, auth, world) -> None:
    def keys(who: str) -> list[str]:
        return [r["key"] for r in ok(api.get("/api/v1/reports", headers=auth(who)))["reports"]]

    assert "follow_ups" in keys("alpha.manager") and "follow_ups" in keys("alpha.admin")
    assert "follow_ups" not in keys("alpha.agent1")


# --- the drafts ---------------------------------------------------------------------------------


def test_every_state_is_counted_per_rule(api, auth, world, db_session) -> None:
    target = lead(db_session, world)
    for _ in range(3):
        draft(db_session, world, target, "approved", decided_after=timedelta(minutes=10))
    draft(db_session, world, target, "approved", edited=True, decided_after=timedelta(minutes=50))
    draft(db_session, world, target, "rejected", decided_after=timedelta(minutes=20))
    draft(db_session, world, target, "expired")
    draft(db_session, world, target, "failed")
    draft(db_session, world, target, "pending")
    (row,) = rows(report(api, auth), 0)
    assert row["rule"] == "Follow-up task due today"
    assert (row["drafts"], row["approved"], row["reworded"], row["rejected"]) == (8, 4, 1, 1)
    assert (row["expired"], row["failed"], row["waiting"]) == (1, 1, 1)
    assert row["approved_share"] == "80.0"  # 4 of the 5 decided
    assert row["reworded_share"] == "25.0"  # 1 of the 4 approved
    assert row["median_minutes_to_decision"] == "10.0"  # 10, 10, 10, 50, 20 -> 10


def test_only_drafts_made_in_the_period_count(api, auth, world, db_session) -> None:
    target = lead(db_session, world)
    draft(db_session, world, target, "approved")
    draft(db_session, world, target, "approved", created=OUTSIDE)
    draft(db_session, world, target, "approved", created=datetime(2026, 11, 9, 23, 0, tzinfo=UTC))
    (row,) = rows(report(api, auth), 0)
    assert row["drafts"] == 1


def test_other_ai_proposals_are_not_follow_ups(api, auth, world, db_session) -> None:
    target = lead(db_session, world)
    draft(db_session, world, target, "approved", agent="staff_assistant")
    assert rows(report(api, auth), 0) == []


def test_an_empty_period_has_no_rows(api, auth, world) -> None:
    body = report(api, auth)
    assert rows(body, 0) == [] and rows(body, 1) == []


def test_another_organisations_drafts_never_count(api, auth, world, db_session) -> None:
    theirs = lead(db_session, world, org="beta")
    draft(db_session, world, theirs, "approved", org="beta")
    assert rows(report(api, auth), 0) == []


# --- replies ------------------------------------------------------------------------------------


def test_a_reply_within_two_weeks_of_the_approval_counts(api, auth, world, db_session) -> None:
    answered = lead(db_session, world, "Answered")
    late = lead(db_session, world, "Late")
    early = lead(db_session, world, "Early")
    silent = lead(db_session, world, "Silent")
    approved_at = INSIDE + timedelta(minutes=30)
    for target in (answered, late, early, silent):
        draft(db_session, world, target, "approved")
    reply(db_session, world, answered, approved_at + timedelta(days=3))
    reply(db_session, world, late, approved_at + timedelta(days=15))  # after the window
    reply(db_session, world, early, approved_at - timedelta(hours=1))  # before the follow-up
    (row,) = rows(report(api, auth), 1)
    assert (row["sent"], row["replied"], row["reply_share"]) == (4, 1, "25.0")


def test_only_approved_follow_ups_are_followed_up_on(api, auth, world, db_session) -> None:
    target = lead(db_session, world)
    draft(db_session, world, target, "rejected")
    reply(db_session, world, target, INSIDE + timedelta(days=1))
    assert rows(report(api, auth), 1) == []


def test_another_organisations_reply_does_not_count(api, auth, world, db_session) -> None:
    ours = lead(db_session, world)
    draft(db_session, world, ours, "approved")
    theirs = lead(db_session, world, org="beta")
    reply(db_session, world, theirs, INSIDE + timedelta(days=1), org="beta")
    (row,) = rows(report(api, auth), 1)
    assert (row["sent"], row["replied"]) == (1, 0)


# --- nothing personal ---------------------------------------------------------------------------


def test_the_report_and_its_file_hold_aggregates_only(api, auth, world, db_session) -> None:
    target = lead(db_session, world, "Zyxwvuts")
    draft(db_session, world, target, "rejected")
    draft(db_session, world, target, "approved")
    shown = api.get(URL, params=PARAMS, headers=auth("alpha.manager")).text
    csv = api.get(f"{URL}/csv", params=PARAMS, headers=auth("alpha.manager")).text
    for text in (shown, csv):
        for secret in ("Zyxwvuts", "Kokapet", "98765", "Zyxwvu private", "right moment"):
            assert secret not in text, secret
        assert str(target.id) not in text
    assert "Follow-up drafts" in csv and "Replies within" in csv


def test_a_reply_before_that_leads_own_follow_up_does_not_count(
    api, auth, world, db_session
) -> None:
    """Two follow-ups a day apart: the second lead wrote before ITS follow-up (but after the first
    one's), so that is not a reply to the follow-up."""
    first = lead(db_session, world, "First")
    second = lead(db_session, world, "Second")
    draft(db_session, world, first, "approved")
    draft(db_session, world, second, "approved", created=INSIDE + timedelta(days=1))
    reply(db_session, world, second, INSIDE + timedelta(hours=5))  # before its own approval
    (row,) = rows(report(api, auth), 1)
    assert (row["sent"], row["replied"]) == (2, 0)
