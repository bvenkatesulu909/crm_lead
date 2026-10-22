# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Domain events and notifications (ADR 0006, step 17a), through the real API and the worker.

People come from test_quotes_api.py: tenant alpha has admin, manager, manager2, agent1 (owns
A1), agent2, support, customers; tenant beta has admin and agent. The worker runs in the test
with an in-memory mailer.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.events import Event, publish
from app.core.mail import MemoryMailer
from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.activities.models import Activity
from app.modules.identity.models import User
from app.modules.leads.models import Lead
from app.modules.notifications import service as notifications
from app.modules.notifications.models import Notification
from app.worker import WorkerServices, job_handlers, run_due_jobs, run_schedules
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for, setup_lead_context
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    Headers,
    World,
    api,
    auth,
    code_of,
    new_quote,
    ok,
    step,
    world,
)

NOTES = "/api/v1/notifications"


@pytest.fixture
def mailer() -> MemoryMailer:
    return MemoryMailer()


@pytest.fixture
def worker(db_connection: Connection, mailer: MemoryMailer) -> Any:
    settings = Settings(
        _env_file=None, database_url=UNREACHABLE_DATABASE_URL, oidc_issuer=TEST_ISSUER
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, MemoryFileStore(), mailer))

    def run() -> int:
        run_schedules(factory)
        return run_due_jobs(factory, handlers, settings)

    return run


def inbox(api: TestClient, auth: Headers, user: str, **params: Any) -> Any:
    return ok(api.get(NOTES, params=params, headers=auth(user)))


def titles(api, auth, user: str) -> list[str]:
    return [n["title"] for n in inbox(api, auth, user)["items"]]


def uid(world: World, name: str) -> uuid.UUID:
    return world.users[name].id


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.agent1"].tenant_id


def add_lead(db_session: Session, world: World, owner: str = "alpha.manager") -> Lead:
    setup_lead_context(db_session, alpha(world), uid(world, owner))
    lead = Lead(
        tenant_id=alpha(world), first_name="Ada", last_name="Lovelace", owner_id=uid(world, owner)
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def lead_event(world: World, lead: Lead, assignee: str) -> Event:
    data = {"lead_id": str(lead.id), "assignee_id": str(uid(world, assignee))}
    return Event(uuid.uuid4(), alpha(world), "lead.assigned", data, 0)


# --- events ------------------------------------------------------------------------------


def test_events_carry_ids_only_and_need_a_known_name(db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(ValueError, match="unknown event"):
        publish(db_session, alpha(world), "lead.deleted_everything", {})
    event_id = publish(db_session, alpha(world), "lead.assigned", {"lead_id": str(lead.id)})
    job = db_session.get(OutboxJob, event_id)
    assert job is not None
    assert (job.kind, job.payload) == (
        "event.lead.assigned",
        {"data": {"lead_id": str(lead.id)}, "depth": 0},
    )


# --- who is told what ----------------------------------------------------------------------


def test_assigning_a_lead_notifies_the_new_owner(api, auth, world, worker, db_session) -> None:
    lead = add_lead(db_session, world)
    ok(
        api.post(
            f"/api/v1/leads/{lead.id}/assign",
            json={"owner_id": str(uid(world, "alpha.agent1"))},
            headers=auth("alpha.manager"),
        )
    )
    worker()
    [note] = inbox(api, auth, "alpha.agent1")["items"]
    assert (note["title"], note["link"], note["read_at"]) == (
        "Lead assigned to you: Ada Lovelace",
        f"/leads/{lead.id}",
        None,
    )
    assert titles(api, auth, "alpha.manager") == []  # the person who did it isn't told
    assert titles(api, auth, "alpha.agent2") == []


# fmt: skip


def test_a_task_for_someone_else_notifies_them(api, auth, world, worker) -> None:
    body = {
        "kind": "task",
        "subject": "Call back about pricing",
        "assignee_id": str(uid(world, "alpha.agent1")),
    }
    ok(api.post("/api/v1/activities", json=body, headers=auth("alpha.manager")), 201)
    ok(
        api.post(
            "/api/v1/activities",
            json={"kind": "task", "subject": "My own task"},
            headers=auth("alpha.agent2"),
        ),
        201,
    )
    worker()
    assert titles(api, auth, "alpha.agent1") == ["New task for you: Call back about pricing"]
    assert titles(api, auth, "alpha.agent2") == []  # your own task is no news


# fmt: skip


def test_quote_approval_flow_notifies_the_right_people(api, auth, world, worker, mailer) -> None:
    lines = [{"product_id": str(world.ids["P1"]), "quantity": "1", "discount_percent": "25"}]
    quote = ok(step(api, auth, "alpha.agent1", new_quote(api, auth, world, lines=lines), "submit"))
    worker()
    label = f"QT-{quote['number']:04d}: 50 widgets"
    for approver in ("alpha.manager", "alpha.manager2", "alpha.admin"):
        assert titles(api, auth, approver) == [f"Approval needed: {label}"]
    assert titles(api, auth, "alpha.agent1") == []  # the owner can't approve their own quote
    assert titles(api, auth, "alpha.support") == []
    # Approval requests come by e-mail by default.
    assert sorted(m.to[0] for m in mailer.sent) == [
        "alpha.admin@example.test",
        "alpha.manager2@example.test",
        "alpha.manager@example.test",
    ]

    ok(step(api, auth, "alpha.manager", quote, "approve"))
    worker()
    assert titles(api, auth, "alpha.agent1") == [f"Quote approved: {label}"]


# fmt: skip


def test_a_customer_accepting_notifies_the_owner(api, auth, world, worker) -> None:
    quote = new_quote(api, auth, world)
    quote = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    quote = ok(step(api, auth, "alpha.agent1", quote, "send"))
    ok(
        api.post(
            f"/api/v1/portal/quotes/{quote['id']}/accept",
            json={"version": quote["version"]},
            headers=auth("alpha.customer"),
        )
    )
    worker()
    assert titles(api, auth, "alpha.agent1") == [
        f"Customer accepted: QT-{quote['number']:04d}: 50 widgets"
    ]


# fmt: skip


def test_no_notification_about_a_record_you_cannot_see(db_session, world) -> None:
    lead = add_lead(db_session, world, owner="alpha.agent1")
    event = lead_event(world, lead, "alpha.agent2")
    assert notifications.on_event(db_session, event) == 0  # agent2 may not see agent1's lead


def test_inactive_people_and_other_tenants_are_never_notified(db_session, world) -> None:
    lead = add_lead(db_session, world, owner="alpha.agent1")
    db_session.execute(
        update(User).where(User.id == uid(world, "alpha.agent1")).values(is_active=False)
    )
    inactive = Event(
        uuid.uuid4(),
        alpha(world),
        "lead.assigned",
        {"lead_id": str(lead.id), "assignee_id": str(uid(world, "alpha.agent1"))},
        0,
    )
    assert notifications.on_event(db_session, inactive) == 0
    other_tenant = Event(
        uuid.uuid4(),
        alpha(world),
        "lead.assigned",
        {"lead_id": str(lead.id), "assignee_id": str(uid(world, "beta.admin"))},
        0,
    )
    assert notifications.on_event(db_session, other_tenant) == 0


# fmt: skip


def test_an_event_delivered_twice_notifies_once(db_session, world) -> None:
    lead = add_lead(db_session, world, owner="alpha.agent1")
    event = lead_event(world, lead, "alpha.agent1")
    assert notifications.on_event(db_session, event) == 1
    assert notifications.on_event(db_session, event) == 0
    assert len(db_session.scalars(select(Notification)).all()) == 1


# --- reminders -----------------------------------------------------------------------------


def test_task_reminders_are_sent_once(api, auth, world, worker, mailer, db_session) -> None:
    now = datetime.now(UTC)
    task = Activity(
        tenant_id=alpha(world), kind="task", subject="Send the contract", status="open",
        assignee_id=uid(world, "alpha.agent1"), created_by_user_id=uid(world, "alpha.agent1"),
        due_at=now + timedelta(hours=2), reminder_at=now - timedelta(minutes=1),
    )  # fmt: skip
    later = Activity(
        tenant_id=alpha(world), kind="task", subject="Not yet", status="open",
        assignee_id=uid(world, "alpha.agent1"), reminder_at=now + timedelta(days=1),
    )  # fmt: skip
    db_session.add_all([task, later])
    db_session.flush()
    worker()
    assert titles(api, auth, "alpha.agent1") == ["Reminder: Send the contract"]
    [mail] = mailer.sent  # reminders come by e-mail by default
    assert (mail.to, mail.subject) == (
        ("alpha.agent1@example.test",),
        "Reminder: Send the contract",
    )
    assert "/notifications/settings" in mail.text
    worker()
    assert len(titles(api, auth, "alpha.agent1")) == 1 and len(mailer.sent) == 1
    db_session.refresh(task)
    assert task.reminder_sent_at is not None


# fmt: skip


def test_changing_the_reminder_time_arms_it_again(api, auth, world, worker, db_session) -> None:
    created = ok(
        api.post(
            "/api/v1/activities",
            json={
                "kind": "task",
                "subject": "Prepare demo",
                "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                "reminder_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
            headers=auth("alpha.agent1"),
        ),
        201,
    )
    task = db_session.get(Activity, uuid.UUID(created["id"]))
    assert task is not None
    task.reminder_sent_at = datetime.now(UTC)  # pretend it was announced
    db_session.flush()
    moved = ok(
        api.patch(
            f"/api/v1/activities/{created['id']}",
            json={
                "version": task.version,  # bumped by the change above
                "reminder_at": (datetime.now(UTC) + timedelta(hours=5)).isoformat(),
            },
            headers=auth("alpha.agent1"),
        )
    )
    db_session.refresh(task)
    assert task.reminder_sent_at is None and moved["id"] == created["id"]


# fmt: skip


# --- the person's inbox ------------------------------------------------------------------


def test_reading_and_privacy_of_the_inbox(api, auth, world, worker, db_session) -> None:
    for _ in range(2):
        lead = add_lead(db_session, world)
        ok(
            api.post(
                f"/api/v1/leads/{lead.id}/assign",
                json={"owner_id": str(uid(world, "alpha.agent1"))},
                headers=auth("alpha.manager"),
            )
        )
    worker()
    box = inbox(api, auth, "alpha.agent1")
    assert box["unread"] == 2
    first = box["items"][0]["id"]
    # Someone else's notification: 404, never "forbidden".
    for user in ("alpha.agent2", "alpha.manager", "beta.admin"):
        assert api.post(f"{NOTES}/{first}/read", headers=auth(user)).status_code == 404
        assert inbox(api, auth, user)["unread"] == 0
    assert api.post(f"{NOTES}/{first}/read", headers=auth("alpha.agent1")).status_code == 204
    assert inbox(api, auth, "alpha.agent1")["unread"] == 1
    assert len(inbox(api, auth, "alpha.agent1", unread_only=True)["items"]) == 1
    assert api.post(f"{NOTES}/read-all", headers=auth("alpha.agent1")).status_code == 204
    assert inbox(api, auth, "alpha.agent1")["unread"] == 0


# fmt: skip


def test_customers_have_no_staff_notifications(api, auth, world) -> None:
    assert api.get(NOTES, headers=auth("alpha.customer")).status_code == 403


def test_e_mail_preferences(api, auth, world, worker, mailer, db_session) -> None:
    prefs = {
        p["type"]: p["email"]
        for p in ok(api.get(f"{NOTES}/preferences", headers=auth("alpha.agent1")))
    }
    assert prefs["activity.reminder_due"] is True and prefs["lead.assigned"] is False
    updated = ok(
        api.put(
            f"{NOTES}/preferences",
            json={"items": [{"type": "lead.assigned", "email": True}]},
            headers=auth("alpha.agent1"),
        )
    )
    assert {p["type"]: p["email"] for p in updated}["lead.assigned"] is True
    assert (
        api.put(
            f"{NOTES}/preferences",
            json={"items": [{"type": "nonsense", "email": True}]},
            headers=auth("alpha.agent1"),
        ).status_code
        == 422
    )
    assert (
        api.put(
            f"{NOTES}/preferences", json={"items": [], "user_id": "x"}, headers=auth("alpha.agent1")
        ).status_code
        == 422
    )

    lead = add_lead(db_session, world)
    ok(
        api.post(
            f"/api/v1/leads/{lead.id}/assign",
            json={"owner_id": str(uid(world, "alpha.agent1"))},
            headers=auth("alpha.manager"),
        )
    )
    worker()
    assert [m.subject for m in mailer.sent] == ["Lead assigned to you: Ada Lovelace"]
    # Another person's preferences are their own.
    other = {
        p["type"]: p["email"]
        for p in ok(api.get(f"{NOTES}/preferences", headers=auth("alpha.agent2")))
    }
    assert other["lead.assigned"] is False


# fmt: skip
