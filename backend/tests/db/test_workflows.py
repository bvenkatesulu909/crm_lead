# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Workflow rules (ADR 0006, step 17b) through the real API, events and the worker.

People come from test_quotes_api.py: tenant alpha has admin, manager, manager2, agent1 (owns
A1), agent2 (owns A2), support, customers; tenant beta has admin and agent (owns B1).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.events import Event
from app.core.mail import MemoryMailer
from app.core.storage import MemoryFileStore
from app.modules.accounts.models import Account
from app.modules.activities.models import Activity
from app.modules.identity.models import User
from app.modules.leads.models import Lead
from app.modules.notifications.models import Notification
from app.modules.quotes.models import Quote
from app.modules.workflows import service as engine
from app.modules.workflows.models import WorkflowRule, WorkflowRun
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

RULES = "/api/v1/workflows/rules"
TASK = {
    "type": "create_task",
    "subject": "Check discount on {record}",
    "due_in_days": 2,
    "assignee": "owner",
}
BIG_DISCOUNT = [{"field": "max_discount_percent", "op": "gt", "value": 20}]


@pytest.fixture
def worker(db_connection: Connection) -> Any:
    settings = Settings(
        _env_file=None, database_url=UNREACHABLE_DATABASE_URL, oidc_issuer=TEST_ISSUER
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(settings, MemoryFileStore(), MemoryMailer()))

    def run() -> int:
        run_schedules(factory, settings)
        return run_due_jobs(factory, handlers, settings)

    return run


def rule(api: TestClient, auth: Headers, user: str = "alpha.admin", **body: Any) -> Any:
    payload = {
        "name": "Big discounts",
        "trigger": "quote.approval_requested",
        "conditions": BIG_DISCOUNT,
        "actions": [TASK],
        **body,
    }
    return api.post(RULES, json=payload, headers=auth(user))


def quote_with_discount(
    api, auth, world, discount: str, user: str = "alpha.agent1", **kw: Any
) -> Any:
    lines = [
        {
            "product_id": str(world.ids[kw.pop("product", "P1")]),
            "quantity": "1",
            "discount_percent": discount,
        }
    ]
    return ok(
        step(api, auth, user, new_quote(api, auth, world, user=user, lines=lines, **kw), "submit")
    )


def tasks(db_session: Session, tenant: uuid.UUID, subject_start: str) -> list[Activity]:
    # Explicit RLS context: the worker binds every tenant in turn, so whatever it left on the
    # shared test connection is not necessarily this one.
    bind_tenant(db_session, tenant)
    return list(
        db_session.scalars(select(Activity).where(Activity.subject.like(f"{subject_start}%")))
    )


def runs(db_session: Session, tenant: uuid.UUID) -> list[WorkflowRun]:
    bind_tenant(db_session, tenant)
    return list(db_session.scalars(select(WorkflowRun).order_by(WorkflowRun.created_at)))


def editable(rule_body: dict[str, Any], **changes: Any) -> dict[str, Any]:
    keys = ("name", "is_active", "trigger", "days", "conditions", "actions")
    return {k: rule_body[k] for k in keys} | changes


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.agent1"].tenant_id


# --- managing rules -------------------------------------------------------------------------


def test_admins_manage_rules(api, auth, world, db_session) -> None:
    created = ok(rule(api, auth), 201)
    assert (created["version"], created["conditions"]) == (
        1,
        [{"field": "max_discount_percent", "op": "gt", "value": "20"}],
    )
    assert ok(api.get(RULES, headers=auth("alpha.admin")))[0]["id"] == created["id"]
    changed = ok(
        api.put(
            f"{RULES}/{created['id']}",
            json=editable(created, is_active=False, version=1),
            headers=auth("alpha.admin"),
        )
    )
    assert (changed["is_active"], changed["version"]) == (False, 2)
    stale = api.put(
        f"{RULES}/{created['id']}", json=editable(created, version=1), headers=auth("alpha.admin")
    )
    assert code_of(stale) == (409, "version_conflict")
    assert api.delete(f"{RULES}/{created['id']}", headers=auth("alpha.admin")).status_code == 204
    actions = db_session.scalars(
        select(AuditLog.action).where(AuditLog.action.like("workflow_rule.%"))
    ).all()
    assert sorted(actions) == [
        "workflow_rule.created",
        "workflow_rule.deleted",
        "workflow_rule.updated",
    ]
    catalogue = ok(api.get("/api/v1/workflows/catalogue", headers=auth("alpha.admin")))
    assert {t["key"] for t in catalogue["triggers"]} >= {"lead.assigned", "schedule.task_overdue"}


@pytest.mark.parametrize(
    "user", ["alpha.manager", "alpha.agent1", "alpha.support", "alpha.customer"]
)
def test_only_tenant_admins_manage_rules(api, auth, world, user) -> None:
    assert rule(api, auth, user=user).status_code == 403
    assert api.get(RULES, headers=auth(user)).status_code == 403
    assert api.get("/api/v1/workflows/runs", headers=auth(user)).status_code == 403


def test_rules_belong_to_one_organisation(api, auth, world) -> None:
    created = ok(rule(api, auth), 201)
    assert ok(api.get(RULES, headers=auth("beta.admin"))) == []
    for method in ("get", "delete"):
        assert (
            getattr(api, method)(f"{RULES}/{created['id']}", headers=auth("beta.admin")).status_code
            == 404
        )
    assert (
        api.put(
            f"{RULES}/{created['id']}",
            json=editable(created, version=1),
            headers=auth("beta.admin"),
        ).status_code
        == 404
    )
    # A colleague from another organisation can't be named in a rule.
    beta_person = world.users["beta.agent"].id
    other = rule(
        api, auth, actions=[{"type": "notify", "message": "x", "to": f"user:{beta_person}"}]
    )
    assert code_of(other) == (422, "invalid_rule")
    assert rule(api, auth, tenant_id=str(uuid.uuid4())).status_code == 422  # no extra fields


def test_invalid_rules_explain_why(api, auth, world) -> None:
    bad = rule(api, auth, conditions=[{"field": "password", "op": "eq", "value": "x"}])
    assert code_of(bad) == (422, "invalid_rule")
    assert "Unknown field" in bad.json()["detail"]


# --- the engine -------------------------------------------------------------------------------


def test_a_matching_event_runs_the_actions(api, auth, world, worker, db_session) -> None:
    notify = {"type": "notify", "message": "Big discount to review", "to": "role:sales_manager"}
    ok(rule(api, auth, actions=[TASK, notify]), 201)
    small = quote_with_discount(api, auth, world, "15")  # needs approval, but only 15 %
    big = quote_with_discount(api, auth, world, "25")
    worker()

    [task] = tasks(db_session, alpha(world), "Check discount on")
    assert task.subject == f"Check discount on QT-{big['number']:04d}: 50 widgets"
    assert (task.assignee_id, task.account_id, task.status) == (
        world.users["alpha.agent1"].id,
        world.ids["A1"],
        "open",
    )
    automation = db_session.get(User, task.created_by_user_id)
    assert automation is not None and (automation.user_type, automation.display_name) == (
        "automation",
        "Automation",
    )
    assert task.due_at is not None and task.due_at > datetime.now(UTC) + timedelta(days=1)

    bind_tenant(db_session, alpha(world))
    managers = db_session.scalars(
        select(Notification.user_id).where(Notification.type == "workflow.message")
    ).all()
    assert set(managers) == {world.users["alpha.manager"].id, world.users["alpha.manager2"].id}
    [run] = runs(db_session, alpha(world))
    assert (run.status, run.record_id, run.message) == (
        "done",
        uuid.UUID(big["id"]),
        "task created; 2 notified",
    )
    assert uuid.UUID(small["id"]) not in {r.record_id for r in runs(db_session, alpha(world))}
    # The run log is visible to admins.
    log = ok(api.get("/api/v1/workflows/runs", headers=auth("alpha.admin")))
    assert (log[0]["rule_name"], log[0]["status"]) == ("Big discounts", "done")


def test_rules_never_reach_another_organisation(api, auth, world, worker, db_session) -> None:
    ok(rule(api, auth, user="beta.admin", conditions=[]), 201)  # beta: every approval request
    quote_with_discount(api, auth, world, "25")  # in alpha
    worker()
    beta = world.users["beta.admin"].tenant_id
    for tenant in (alpha(world), beta):  # checked per tenant: RLS shows one at a time
        assert runs(db_session, tenant) == [] and tasks(db_session, tenant, "Check discount") == []


def test_inactive_rules_do_nothing(api, auth, world, worker, db_session) -> None:
    ok(rule(api, auth, is_active=False), 201)
    quote_with_discount(api, auth, world, "25")
    worker()
    assert runs(db_session, alpha(world)) == []


def test_lead_status_is_changed_through_the_leads_rules(
    api, auth, world, worker, db_session
) -> None:
    ok(
        rule(
            api,
            auth,
            name="Contact assigned leads",
            trigger="lead.assigned",
            conditions=[{"field": "status", "op": "eq", "value": "new"}],
            actions=[{"type": "update_field", "field": "lead.status", "value": "contacted"}],
        ),
        201,
    )
    setup_lead_context(db_session, alpha(world), world.users["alpha.manager"].id)
    lead = Lead(
        tenant_id=alpha(world), last_name="Example", owner_id=world.users["alpha.manager"].id
    )
    db_session.add(lead)
    db_session.flush()
    ok(
        api.post(
            f"/api/v1/leads/{lead.id}/assign",
            json={"owner_id": str(world.users["alpha.agent1"].id)},
            headers=auth("alpha.manager"),
        )
    )
    worker()
    setup_lead_context(db_session, alpha(world), world.users["alpha.manager"].id, scope="all")
    db_session.refresh(lead)
    assert lead.status == "contacted"
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "lead.status_changed")
    ).one()
    assert audit.actor_subject == f"automation:{alpha(world)}"
    assert audit.changes["reason"] == "Workflow rule: Contact assigned leads"


def test_customer_segment_is_changed_through_the_accounts_rules(
    api, auth, world, worker, db_session
) -> None:
    ok(
        rule(
            api,
            auth,
            name="Accepted big deals",
            trigger="quote.accepted",
            conditions=[],
            actions=[{"type": "update_field", "field": "account.segment", "value": "enterprise"}],
        ),
        201,
    )
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
    account = db_session.get(Account, world.ids["A1"])
    assert account is not None
    db_session.refresh(account)
    assert account.segment == "enterprise"


def test_a_failing_action_is_logged_and_undone(api, auth, world, worker, db_session) -> None:
    # "qualified" -> "new" is not allowed: the whole run is undone, the error is logged.
    ok(
        rule(
            api,
            auth,
            name="Breaks",
            trigger="lead.assigned",
            conditions=[],
            actions=[
                TASK | {"subject": "Should not exist"},
                {"type": "update_field", "field": "lead.status", "value": "new"},
            ],
        ),
        201,
    )
    ok(
        rule(
            api,
            auth,
            name="Works",
            trigger="lead.assigned",
            conditions=[],
            actions=[TASK | {"subject": "Still works"}],
        ),
        201,
    )
    setup_lead_context(db_session, alpha(world), world.users["alpha.manager"].id)
    lead = Lead(
        tenant_id=alpha(world),
        last_name="Done",
        owner_id=world.users["alpha.manager"].id,
        status="qualified",
    )
    db_session.add(lead)
    db_session.flush()
    ok(
        api.post(
            f"/api/v1/leads/{lead.id}/assign",
            json={"owner_id": str(world.users["alpha.agent1"].id)},
            headers=auth("alpha.manager"),
        )
    )
    worker()
    by_rule = {r.rule_id: r for r in runs(db_session, alpha(world))}
    assert sorted(r.status for r in by_rule.values()) == ["done", "failed"]
    [failed] = [r for r in by_rule.values() if r.status == "failed"]
    assert failed.message == "A lead cannot go from 'qualified' to 'new'."
    assert (
        tasks(db_session, alpha(world), "Should not exist") == []
        and len(tasks(db_session, alpha(world), "Still works")) == 1
    )


def test_loops_and_floods_are_stopped(api, auth, world, db_session) -> None:
    created = ok(rule(api, auth, conditions=[]), 201)
    rule_row = db_session.get(WorkflowRule, uuid.UUID(created["id"]))
    quote = quote_with_discount(api, auth, world, "25")

    def event(depth: int) -> Event:
        return Event(
            uuid.uuid4(), alpha(world), "quote.approval_requested", {"quote_id": quote["id"]}, depth
        )

    engine.on_event(db_session, event(3), hourly_limit=100)  # caused by 3 automatic steps
    engine.on_event(db_session, event(0), hourly_limit=100)
    engine.on_event(db_session, event(0), hourly_limit=1)  # second run within the hour
    assert [(r.status, (r.message or "")[:13]) for r in runs(db_session, alpha(world))] == [
        ("limited", "Stopped: star"),
        ("done", "task created"),
        ("limited", "Stopped: the "),
    ]
    same = event(0)
    engine.on_event(db_session, same, hourly_limit=100)
    engine.on_event(db_session, same, hourly_limit=100)  # the worker delivered it twice
    assert len(runs(db_session, alpha(world))) == 4 and rule_row is not None


def test_actions_publish_events_one_level_deeper(api, auth, world, worker, db_session) -> None:
    from app.core.outbox import OutboxJob

    ok(
        rule(
            api,
            auth,
            conditions=[],
            actions=[TASK | {"assignee": f"user:{world.users['alpha.agent2'].id}"}],
        ),
        201,
    )
    quote_with_discount(api, auth, world, "25")
    worker()
    [assigned] = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "event.activity.assigned")
    ).all()
    assert assigned.payload["depth"] == 1  # caused by an automatic step


def test_notifications_only_reach_people_who_may_see_the_record(
    api, auth, world, worker, db_session
) -> None:
    ok(
        rule(
            api,
            auth,
            conditions=[],
            actions=[{"type": "notify", "message": "Look", "to": "role:sales_agent"}],
        ),
        201,
    )
    quote_with_discount(api, auth, world, "25")  # agent1's quote: agent2 may not see it
    worker()
    bind_tenant(db_session, alpha(world))
    told = set(
        db_session.scalars(
            select(Notification.user_id).where(Notification.type == "workflow.message")
        )
    )
    assert told == {world.users["alpha.agent1"].id}


# --- schedules ------------------------------------------------------------------------------


def test_expiring_quotes_get_a_follow_up_task_once(api, auth, world, worker, db_session) -> None:
    ok(
        rule(
            api,
            auth,
            name="Expiring",
            trigger="schedule.quote_expiring",
            days=3,
            conditions=[],
            actions=[TASK | {"subject": "Follow up {record}"}],
        ),
        201,
    )
    quote = ok(step(api, auth, "alpha.agent1", quote_with_discount(api, auth, world, "5"), "send"))
    db_session.execute(
        update(Quote)
        .where(Quote.id == uuid.UUID(quote["id"]))
        .values(valid_until=date.today() + timedelta(days=2))
    )
    later = ok(
        step(api, auth, "alpha.agent1", quote_with_discount(api, auth, world, "5"), "send")
    )  # valid 30 days
    worker()
    worker()
    [task] = tasks(db_session, alpha(world), "Follow up")
    assert later["id"] not in task.subject and quote["title"] in task.subject


def test_overdue_tasks_trigger_rules(api, auth, world, worker, db_session) -> None:
    ok(
        rule(
            api,
            auth,
            name="Overdue",
            trigger="schedule.task_overdue",
            days=1,
            conditions=[{"field": "priority", "op": "eq", "value": "high"}],
            actions=[{"type": "notify", "message": "Overdue task", "to": "role:sales_manager"}],
        ),
        201,
    )
    now = datetime.now(UTC)
    for priority in ("high", "low"):
        db_session.add(
            Activity(
                tenant_id=alpha(world),
                kind="task",
                subject=f"Old {priority}",
                status="open",
                priority=priority,
                assignee_id=world.users["alpha.agent1"].id,
                due_at=now - timedelta(days=2),
            )
        )
    db_session.flush()
    worker()
    bind_tenant(db_session, alpha(world))
    titles = db_session.scalars(
        select(Notification.title).where(Notification.type == "workflow.message")
    ).all()
    assert sorted(titles) == ["Overdue task: Old high", "Overdue task: Old high"]  # two managers


def test_the_automation_user_is_not_a_colleague(api, auth, world, worker, db_session) -> None:
    ok(rule(api, auth), 201)
    quote_with_discount(api, auth, world, "25")
    worker()
    users = ok(api.get("/api/v1/tenant/users", headers=auth("alpha.admin")))
    assert "Automation" not in {u["display_name"] for u in users}
    directory = ok(api.get("/api/v1/users", headers=auth("alpha.agent1")))
    assert "Automation" not in {u["display_name"] for u in directory}
