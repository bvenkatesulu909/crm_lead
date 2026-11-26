# ruff: noqa: F811 - pytest fixtures imported from the other tests are used as parameters
"""The follow-up scan (ADR 0036, FM4): a due task on a lead becomes ONE draft in the approval queue.

Nothing is sent by the scan. These tests play the real scan, the real approval queue and the real
worker; only the time is fixed. People come from test_quotes_api.py (agent1 owns the leads here,
manager approves, tenant beta is separate).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.events import Event
from app.modules.activities.models import Activity
from app.modules.approvals import service as approvals
from app.modules.approvals.models import AgentAction
from app.modules.communications import follow_up_rules as rules
from app.modules.communications import repository
from app.modules.communications.models import EmailMessage, EmailTemplate
from app.modules.follow_ups import service as scan_service
from app.modules.identity.models import User
from app.modules.leads.models import Lead
from app.modules.notifications import service as notifications
from app.worker import run_schedules
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for, setup_lead_context
from tests.db.test_approvals import Acting, acting, add_lead, alpha  # noqa: F401
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

NOW = datetime.now(UTC)
SUBJECT_TEMPLATE = "Checking in, {{recipient.first_name}}"
BODY_TEMPLATE = (
    "Hello {{recipient.first_name}},\n\nJust checking in on your enquiry.\n{{sender.name}}"
)


def make_template(db_session: Session, world: World, tenant: str = "alpha", **values: Any):
    admin = world.users[f"{tenant}.admin"]
    bind_tenant(db_session, admin.tenant_id)
    fields = {
        "tenant_id": admin.tenant_id,
        "name": f"Follow-up {uuid.uuid4().hex[:6]}",
        "subject": SUBJECT_TEMPLATE,
        "body": BODY_TEMPLATE,
        "created_by_user_id": admin.id,
    } | values
    template = EmailTemplate(**fields)
    db_session.add(template)
    db_session.flush()
    return template


def switch_on(db_session: Session, world: World, tenant: str = "alpha", **values: Any):
    """Save the organisation's settings: on, with a fresh template, and any changed numbers."""
    template = make_template(db_session, world, tenant)
    admin = world.users[f"{tenant}.admin"]
    policy = rules.Policy(enabled=True, template_id=template.id, **values)
    repository.add_follow_up_policy(db_session, admin.tenant_id, admin.id, policy)
    return template


def due_lead(
    db_session: Session,
    world: World,
    owner: str | None = "alpha.agent1",
    *,
    due: datetime = NOW,
    **lead_values: Any,
) -> Lead:
    """A website lead with an address, owned by ``owner``, with one open task due ``due``."""
    lead = add_lead(db_session, world, owner)
    defaults: dict[str, Any] = {"email": "asha@example.test", "source": "web"}
    for name, value in (defaults | lead_values).items():
        setattr(lead, name, value)
    db_session.flush()
    add_task(db_session, world, lead, due=due)
    return lead


def add_task(
    db_session: Session, world: World, lead: Lead, *, due: datetime, **values: Any
) -> Activity:
    bind_tenant(db_session, alpha(world))
    fields: dict[str, Any] = {
        "tenant_id": alpha(world),
        "kind": "task",
        "subject": "Call back",
        "status": "open",
        "due_at": due,
        "lead_id": lead.id,
        "assignee_id": world.users["alpha.agent1"].id,
        "created_by_user_id": world.users["alpha.agent1"].id,
    }
    task = Activity(**(fields | values))
    db_session.add(task)
    db_session.flush()
    return task


def run_scan(db_session: Session, world: World, **kwargs: Any) -> scan_service.ScanResult:
    bind_tenant(db_session, alpha(world))
    return scan_service.scan(db_session, NOW, tenant_id=alpha(world), **kwargs)


def drafts(db_session: Session, world: World) -> list[AgentAction]:
    bind_tenant(db_session, alpha(world))
    return list(
        db_session.scalars(
            select(AgentAction)
            .where(AgentAction.kind == "communication.send_follow_up")
            .order_by(AgentAction.seq)
        )
    )


def emails(db_session: Session, world: World) -> list[EmailMessage]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(EmailMessage)))


def set_lead(db_session: Session, world: World, lead: Lead, **values: Any) -> None:
    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.execute(update(Lead).where(Lead.id == lead.id).values(**values))
    db_session.flush()


# --- the happy path ---------------------------------------------------------------------------


def test_a_due_task_makes_one_draft_for_the_owner_and_sends_nothing(world, db_session) -> None:
    switch_on(db_session, world)
    lead = due_lead(db_session, world)
    result = run_scan(db_session, world)
    assert (result.made, result.skipped) == (1, {})
    (draft,) = drafts(db_session, world)
    assert (draft.status, draft.agent, draft.target_type, draft.target_id) == (
        "pending",
        "follow_up",
        "lead",
        lead.id,
    )
    assert draft.payload["reason_code"] == "task_due_today"
    assert draft.payload["subject"] == "Checking in, Asha"
    # The sender line is the lead's owner, who will normally approve it.
    assert draft.payload["body"].endswith(world.users["alpha.agent1"].display_name)
    assert abs(draft.expires_at - draft.created_at - timedelta(days=7)) < timedelta(seconds=5)
    assert emails(db_session, world) == []


def test_the_draft_is_asked_for_by_the_automation_identity(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    run_scan(db_session, world)
    (draft,) = drafts(db_session, world)
    requester = db_session.get(User, draft.requested_by_user_id)
    assert requester is not None and requester.user_type == "automation"


def test_running_the_scan_again_makes_no_second_draft(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    run_scan(db_session, world)
    again = run_scan(db_session, world)
    # Both reasons hold: it is waiting, and a draft was made within the cooldown.
    assert again.made == 0 and again.skipped == {"draft_waiting": 1, "cooldown": 1}
    assert len(drafts(db_session, world)) == 1


def test_after_the_owner_approves_it_goes_out_once_and_the_cooldown_holds(
    world, db_session, acting: Acting
) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    run_scan(db_session, world)
    (draft,) = drafts(db_session, world)
    acting.approve("alpha.agent1", draft)
    (message,) = emails(db_session, world)
    assert (message.status, message.to_address) == ("queued", "asha@example.test")
    assert message.sent_by_user_id == world.users["alpha.agent1"].id
    again = run_scan(db_session, world)
    assert again.made == 0 and again.skipped == {"cooldown": 1}


def test_a_rejected_draft_also_starts_the_cooldown(world, db_session, acting: Acting) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    run_scan(db_session, world)
    (draft,) = drafts(db_session, world)
    acting.reject("alpha.agent1", draft, "Not now.")
    assert run_scan(db_session, world).skipped == {"cooldown": 1}


def test_two_due_tasks_on_one_lead_make_one_draft(world, db_session) -> None:
    switch_on(db_session, world)
    lead = due_lead(db_session, world)
    add_task(db_session, world, lead, due=NOW)
    result = run_scan(db_session, world)
    # One draft, and the second task was not even looked at (no "waiting" noise).
    assert (result.made, result.skipped) == (1, {})
    assert len(drafts(db_session, world)) == 1


# --- which tasks count ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task",
    [
        {"due_delta": timedelta(days=1)},  # tomorrow
        {"due_delta": timedelta(days=-1)},  # overdue: it was due on another day
        {"status": "done", "completed_at": NOW},
        {"status": "cancelled"},
    ],
)
def test_only_an_open_task_due_today_counts(world, db_session, task: dict[str, Any]) -> None:
    switch_on(db_session, world)
    lead = add_lead(db_session, world)
    lead.email, lead.source = "asha@example.test", "web"
    due = NOW + task.pop("due_delta", timedelta(0))
    add_task(db_session, world, lead, due=due, **task)
    assert run_scan(db_session, world).made == 0
    assert drafts(db_session, world) == []


def test_a_note_or_a_call_is_not_a_follow_up_task(world, db_session) -> None:
    switch_on(db_session, world)
    lead = add_lead(db_session, world)
    lead.email, lead.source = "asha@example.test", "web"
    add_task(db_session, world, lead, due=NOW, kind="call")
    assert run_scan(db_session, world).made == 0


# --- the switches -----------------------------------------------------------------------------


def test_nothing_happens_before_an_administrator_switches_it_on(world, db_session) -> None:
    due_lead(db_session, world)
    result = run_scan(db_session, world)
    assert (result.made, result.skipped) == (0, {})
    assert drafts(db_session, world) == []


def test_switching_it_off_stops_new_drafts(world, db_session) -> None:
    template = switch_on(db_session, world)
    due_lead(db_session, world)
    admin = world.users["alpha.admin"]
    repository.add_follow_up_policy(
        db_session, admin.tenant_id, admin.id, rules.Policy(enabled=False, template_id=template.id)
    )
    assert run_scan(db_session, world).made == 0


def test_the_platform_switch_stops_every_organisation(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    stopped = run_scan(db_session, world, platform_enabled=False)
    # Stopped before any lead was read: nothing made and nothing even looked at.
    assert (stopped.made, stopped.skipped) == (0, {})
    assert drafts(db_session, world) == []


# --- the stop conditions, seen through the real scan ------------------------------------------


def test_a_lead_who_withdrew_consent_gets_no_draft(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world, email_consent="withdrawn", email_consent_at=NOW)
    result = run_scan(db_session, world)
    assert result.made == 0 and result.skipped == {"consent_withdrawn": 1}


def test_a_lead_without_an_address_gets_no_draft(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world, email=None)
    assert run_scan(db_session, world).skipped == {"no_address": 1}


def test_a_closed_lead_is_not_chased(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world, status="unqualified")
    assert run_scan(db_session, world).skipped == {"lead_closed": 1}


def test_a_lead_nobody_owns_gets_no_draft(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world, owner=None)
    assert run_scan(db_session, world).skipped == {"no_owner": 1}


def test_a_lead_whose_owner_has_left_gets_no_draft(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(User).where(User.id == world.users["alpha.agent1"].id).values(is_active=False)
    )
    db_session.flush()
    result = run_scan(db_session, world)
    assert result.made == 0 and result.skipped == {"owner_inactive": 1}


def test_unknown_consent_needs_a_conversation_the_person_started(world, db_session) -> None:
    switch_on(db_session, world)
    lead = due_lead(db_session, world, source="referral")  # we found them; they did not write
    assert run_scan(db_session, world).skipped == {"consent_unknown": 1}
    # They wrote to us (someone logged the e-mail): now a service follow-up is fine.
    bind_tenant(db_session, alpha(world))
    db_session.add(
        EmailMessage(
            tenant_id=alpha(world),
            direction="inbound_logged",
            status="logged",
            lead_id=lead.id,
            to_address="team@example.test",
            subject="Question",
            body="Is the plot still available?",
            sent_by_user_id=world.users["alpha.agent1"].id,
        )
    )
    db_session.flush()
    # ... but a reply that arrived AFTER the task was set means they already answered.
    assert run_scan(db_session, world).skipped == {"reply_received": 1}


def test_granted_consent_allows_a_lead_we_found_ourselves(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world, source="referral", email_consent="granted", email_consent_at=NOW)
    assert run_scan(db_session, world).made == 1


def test_a_reply_before_the_task_does_not_stop_the_follow_up(world, db_session) -> None:
    switch_on(db_session, world)
    lead = add_lead(db_session, world)
    lead.email, lead.source = "asha@example.test", "referral"
    bind_tenant(db_session, alpha(world))
    db_session.add(
        EmailMessage(
            tenant_id=alpha(world),
            direction="inbound_logged",
            status="logged",
            lead_id=lead.id,
            to_address="team@example.test",
            subject="Question",
            body="Is the plot still available?",
            sent_by_user_id=world.users["alpha.agent1"].id,
            created_at=NOW - timedelta(days=2),
        )
    )
    db_session.flush()
    add_task(db_session, world, lead, due=NOW)
    assert run_scan(db_session, world).made == 1


# --- the text of the draft --------------------------------------------------------------------


def test_a_template_with_a_hole_makes_no_draft(world, db_session) -> None:
    switch_on(db_session, world)  # uses the company, which this lead does not have
    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(EmailTemplate).values(body="Hello {{recipient.first_name}} of {{recipient.company}}")
    )
    db_session.flush()
    due_lead(db_session, world)
    assert run_scan(db_session, world).skipped == {"template_unusable": 1}


def test_a_template_that_was_deactivated_makes_no_draft(world, db_session) -> None:
    switch_on(db_session, world)
    bind_tenant(db_session, alpha(world))
    db_session.execute(update(EmailTemplate).values(is_active=False))
    db_session.flush()
    due_lead(db_session, world)
    assert run_scan(db_session, world).skipped == {"template_unusable": 1}


def test_text_the_lead_typed_cannot_put_a_link_into_a_draft(world, db_session) -> None:
    """The name comes from the lead record; the safety check reads the finished text."""
    switch_on(db_session, world)
    due_lead(db_session, world, first_name="see https://evil.example.test/pay")
    result = run_scan(db_session, world)
    assert result.made == 0 and result.skipped == {"blocked": 1}
    assert drafts(db_session, world) == []
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "agent_action.blocked")
    ).first()
    assert entry is not None and "evil" not in str(entry.changes)


# --- limits -----------------------------------------------------------------------------------


def test_the_daily_cap_stops_further_drafts(world, db_session) -> None:
    switch_on(db_session, world, daily_cap=2)
    for _ in range(3):
        due_lead(db_session, world)
    result = run_scan(db_session, world)
    assert result.made == 2 and result.skipped == {"daily_cap": 1}


def test_a_run_makes_at_most_its_batch_and_the_next_run_continues(world, db_session) -> None:
    switch_on(db_session, world)
    for _ in range(3):
        due_lead(db_session, world)
    assert run_scan(db_session, world, batch=2).made == 2
    assert run_scan(db_session, world, batch=2).made == 1
    assert len(drafts(db_session, world)) == 3


def test_one_owner_cannot_have_more_than_the_waiting_cap(world, db_session) -> None:
    switch_on(db_session, world, pending_cap=1)
    for _ in range(2):
        due_lead(db_session, world)
    result = run_scan(db_session, world)
    assert result.made == 1 and result.skipped == {"owner_pending_cap": 1}


def test_the_asker_allowances_do_not_throttle_a_whole_organisation(world, db_session) -> None:
    """The safety check allows 10 proposals an hour per asker by default; the scan asks for the
    whole organisation, so it uses the policy's own caps (here: 100 a day)."""
    switch_on(db_session, world, pending_cap=20)
    for _ in range(12):
        due_lead(db_session, world)
    assert run_scan(db_session, world).made == 12


def test_the_monthly_cap_per_person_counts_earlier_drafts(world, db_session) -> None:
    switch_on(db_session, world, monthly_cap=1, cooldown_days=1)
    lead = due_lead(db_session, world)
    run_scan(db_session, world)
    (draft,) = drafts(db_session, world)
    # Pretend the first draft was made three days ago and has been decided.
    db_session.execute(
        update(AgentAction)
        .where(AgentAction.id == draft.id)
        .values(
            created_at=NOW - timedelta(days=3),
            status="rejected",
            decided_by_user_id=world.users["alpha.manager"].id,
            decided_at=NOW - timedelta(days=2),
            decision_note="No.",
        )
    )
    db_session.flush()
    result = run_scan(db_session, world)
    assert result.made == 0 and result.skipped == {"monthly_cap": 1}
    assert drafts(db_session, world)[0].target_id == lead.id


# --- organisations stay apart -----------------------------------------------------------------


def test_another_organisations_tasks_and_settings_are_left_alone(world, db_session) -> None:
    switch_on(db_session, world, "beta")  # only beta has switched it on
    due_lead(db_session, world)  # alpha's lead, alpha has not
    assert run_scan(db_session, world).made == 0
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(func.count()).select_from(AgentAction)).one() == 0


# --- the owner is told, and the real worker runs it -------------------------------------------


def test_the_owner_and_the_approvers_are_told_a_draft_is_waiting(world, db_session) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    run_scan(db_session, world)
    (draft,) = drafts(db_session, world)
    event = Event(
        id=uuid.uuid4(),
        tenant_id=alpha(world),
        name="agent_action.proposed",
        data={"action_id": str(draft.id)},
        depth=0,
    )
    told = notifications._proposal_approvers(db_session, event)
    assert world.users["alpha.agent1"].id in told  # the owner, who may approve this kind
    assert world.users["alpha.manager"].id in told  # and the managers, as for every proposal
    assert world.users["alpha.agent2"].id not in told  # another agent is not told


def test_the_worker_makes_the_drafts_and_the_platform_switch_stops_it(
    world, db_session, db_connection
) -> None:
    switch_on(db_session, world)
    due_lead(db_session, world)
    factory = session_factory_for(db_connection)

    def settings(**values: Any) -> Settings:
        return Settings(
            _env_file=None,
            database_url=UNREACHABLE_DATABASE_URL,
            oidc_issuer=TEST_ISSUER,
            web_app_url="http://localhost:3000",
            **values,
        )

    run_schedules(factory, settings(follow_ups_disabled=True))
    assert drafts(db_session, world) == []
    run_schedules(factory, settings())
    assert len(drafts(db_session, world)) == 1
    # The worker is safe to run again and again: still one.
    run_schedules(factory, settings())
    assert len(drafts(db_session, world)) == 1
    assert approvals.describe(drafts(db_session, world)[0]).startswith("Send a follow-up e-mail")
