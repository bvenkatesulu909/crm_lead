"""Workflow rules (ADR 0006, step 17b). Functions here never commit: the router (or the worker)
commits once.

The engine, run by the worker:
- for an EVENT trigger, every active rule of that tenant with that trigger is checked;
- for a SCHEDULE trigger, the worker looks for matching records about once a minute.
A rule acts at most once per event (or per record and date). It acts as the tenant's
"Automation" identity, through the owning modules' api.py, so their rules and audit apply.
Loops are stopped: events caused by automation carry a depth, and rules don't act from depth 3.
Each tenant has a limit of automatic actions per hour. Every outcome is written to the run log.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Role
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.events import MAX_DEPTH, Event, caused_by_automation
from app.core.outbox import PermanentJobError
from app.core.records import RecordFacts
from app.modules.accounts import api as accounts_api
from app.modules.activities import api as activities_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.notifications import api as notifications_api
from app.modules.orders import api as orders_api
from app.modules.quotes import api as quotes_api
from app.modules.support import api as support_api
from app.modules.workflows import catalogue, rules
from app.modules.workflows.models import WorkflowRule, WorkflowRun
from app.modules.workflows.schemas import (
    Catalogue,
    FieldOut,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    RunRead,
    TriggerOut,
)

logger = logging.getLogger(__name__)
ENTITY = "workflow_rule"


class RuleNotFoundError(NotFoundError):
    code = "rule_not_found"

    def __init__(self) -> None:
        super().__init__("The rule doesn't exist.")


class VersionConflictError(ConflictError):
    code = "version_conflict"


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise RuleNotFoundError()
    return principal.tenant_id


# --- catalogue and rule management (tenant admins) ---------------------------------------


def _field_out(key: str, label: str, kind: str, options: Sequence[str]) -> FieldOut:
    return FieldOut(key=key, label=label, type=kind, options=list(options))


def get_catalogue() -> Catalogue:
    triggers = []
    for t in catalogue.TRIGGERS.values():
        triggers.append(
            TriggerOut(
                key=t.key,
                label=t.label,
                kind=t.kind,
                record_type=t.record_type,
                days_label=t.days_label,
                fields=[
                    _field_out(f.key, f.label, f.type, f.options)
                    for f in catalogue.RECORD_FIELDS[t.record_type]
                ],
                field_updates=[
                    _field_out(u.key, u.label, "choice", u.options)
                    for u in catalogue.FIELD_UPDATES.values()
                    if t.record_type in u.record_types
                ],
            )
        )
    return Catalogue(
        triggers=triggers,
        operators={k: list(v) for k, v in catalogue.OPERATORS.items()},
        roles=list(catalogue.ROLES),
        max_conditions=catalogue.MAX_CONDITIONS,
        max_actions=catalogue.MAX_ACTIONS,
    )


def _validated(
    session: Session, tenant_id: uuid.UUID, data: RuleCreate
) -> tuple[int | None, list[dict[str, Any]], list[dict[str, Any]]]:
    days, conditions, actions = rules.validate(
        data.trigger, data.days, data.conditions, data.actions
    )
    # Named colleagues must be active staff of THIS organisation (never trust the client).
    for action in actions:
        person = action.get("assignee") or action.get("to") or ""
        if person.startswith("user:") and not identity_api.is_active_staff_member(
            session, tenant_id, uuid.UUID(person[5:])
        ):
            raise rules.InvalidRuleError("Choose an active colleague of your organisation.")
    return days, conditions, actions


def _load(
    session: Session, principal: Principal, rule_id: uuid.UUID, *, lock: bool = False
) -> WorkflowRule:
    query = select(WorkflowRule).where(
        WorkflowRule.tenant_id == _tenant(principal), WorkflowRule.id == rule_id
    )
    if lock:
        query = query.with_for_update()
    rule = session.scalars(query).one_or_none()
    if rule is None:
        raise RuleNotFoundError()
    return rule


def list_rules(session: Session, principal: Principal) -> list[RuleRead]:
    rows = session.scalars(
        select(WorkflowRule)
        .where(WorkflowRule.tenant_id == _tenant(principal))
        .order_by(WorkflowRule.name, WorkflowRule.id)
    ).all()
    return [RuleRead.model_validate(r) for r in rows]


def get_rule(session: Session, principal: Principal, rule_id: uuid.UUID) -> RuleRead:
    return RuleRead.model_validate(_load(session, principal, rule_id))


def create_rule(session: Session, principal: Principal, data: RuleCreate) -> RuleRead:
    tenant_id = _tenant(principal)
    days, conditions, actions = _validated(session, tenant_id, data)
    rule = WorkflowRule(
        tenant_id=tenant_id,
        name=data.name,
        is_active=data.is_active,
        trigger=data.trigger,
        days=days,
        conditions=conditions,
        actions=actions,
        created_by_user_id=principal.user_id,
    )
    session.add(rule)
    session.flush()
    record_audit(
        session,
        principal,
        action="workflow_rule.created",
        entity_type=ENTITY,
        entity_id=rule.id,
        changes={"name": rule.name, "trigger": rule.trigger},
    )
    session.refresh(rule)
    return RuleRead.model_validate(rule)


def update_rule(
    session: Session, principal: Principal, rule_id: uuid.UUID, data: RuleUpdate
) -> RuleRead:
    rule = _load(session, principal, rule_id, lock=True)
    if rule.version != data.version:
        raise VersionConflictError("The rule was changed by someone else. Reload it.")
    days, conditions, actions = _validated(session, rule.tenant_id, data)
    rule.name, rule.is_active, rule.trigger = data.name, data.is_active, data.trigger
    rule.days, rule.conditions, rule.actions = days, conditions, actions
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError("The rule was changed by someone else. Reload it.") from exc
    record_audit(
        session,
        principal,
        action="workflow_rule.updated",
        entity_type=ENTITY,
        entity_id=rule.id,
        changes={"name": rule.name, "is_active": rule.is_active},
    )
    session.refresh(rule)
    return RuleRead.model_validate(rule)


def delete_rule(session: Session, principal: Principal, rule_id: uuid.UUID) -> None:
    rule = _load(session, principal, rule_id, lock=True)
    record_audit(
        session,
        principal,
        action="workflow_rule.deleted",
        entity_type=ENTITY,
        entity_id=rule.id,
        changes={"name": rule.name},
    )
    session.delete(rule)  # its run log goes with it (ON DELETE CASCADE)
    session.flush()


def list_runs(
    session: Session, principal: Principal, *, rule_id: uuid.UUID | None, limit: int
) -> list[RunRead]:
    tenant_id = _tenant(principal)
    query = (
        select(WorkflowRun, WorkflowRule.name)
        .join(
            WorkflowRule,
            (WorkflowRule.id == WorkflowRun.rule_id)
            & (WorkflowRule.tenant_id == WorkflowRun.tenant_id),
        )
        .where(WorkflowRun.tenant_id == tenant_id)
    )
    if rule_id is not None:
        query = query.where(WorkflowRun.rule_id == rule_id)
    rows = session.execute(
        query.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id).limit(limit)
    ).all()
    return [
        RunRead.model_validate(run).model_copy(update={"rule_name": name}) for run, name in rows
    ]


# --- the engine (worker) -------------------------------------------------------------------

FactsLoader = Callable[[Session, Principal, uuid.UUID], RecordFacts | None]
FACTS: dict[str, FactsLoader] = {
    "lead": leads_api.lead_facts,
    "quote": quotes_api.quote_facts,
    "ticket": support_api.ticket_facts,
    "order": orders_api.order_facts,
    "activity": activities_api.activity_facts,
}


def _facts(
    session: Session, principal: Principal, record_type: str, record_id: uuid.UUID
) -> RecordFacts | None:
    return FACTS[record_type](session, principal, record_id)


def _owner(session: Session, automation: Principal, facts: RecordFacts) -> uuid.UUID | None:
    if facts.owner_id is not None:
        return facts.owner_id
    if facts.account_id is not None:  # orders: the customer's owner is responsible
        return accounts_api.account_owner_id(session, automation, facts.account_id)
    return None


def _people(
    session: Session, automation: Principal, facts: RecordFacts, who: str
) -> set[uuid.UUID]:
    if who == "owner":
        owner = _owner(session, automation, facts)
        return {owner} if owner else set()
    if who.startswith("role:"):
        return set(identity_api.staff_with_role(session, facts_tenant(automation), Role(who[5:])))
    return {uuid.UUID(who[5:])}


def facts_tenant(principal: Principal) -> uuid.UUID:
    assert principal.tenant_id is not None  # noqa: S101 - automation always has a tenant
    return principal.tenant_id


def _do(
    session: Session,
    automation: Principal,
    rule: WorkflowRule,
    facts: RecordFacts,
    action: dict[str, Any],
    run_id: uuid.UUID,
    now: datetime,
) -> str:
    """Performs one action; returns a short description for the run log."""
    if action["type"] == "create_task":
        people = _people(session, automation, facts, action["assignee"])
        if not people:
            raise DomainError("The record has no owner to give the task to.")
        activities_api.create_task(
            session,
            automation,
            subject=rules.render(action["subject"], facts.label),
            due_at=now + timedelta(days=action["due_in_days"]),
            assignee_id=next(iter(people)),
            lead_id=facts.lead_id,
            account_id=facts.account_id,
        )
        return "task created"
    if action["type"] == "notify":
        people = _people(session, automation, facts, action["to"])
        sent = notifications_api.notify_users(
            session,
            facts_tenant(automation),
            people,
            title=f"{action['message']}: {facts.label}",
            link=facts.link,
            key=run_id,
            can_see=lambda me: _facts(session, me, facts.record_type, facts.record_id) is not None,
        )
        return f"{sent} notified"
    reason = f"Workflow rule: {rule.name}"
    if action["field"] == "lead.status":
        leads_api.set_lead_status(session, automation, facts.record_id, action["value"], reason)
    else:
        if facts.account_id is None:
            raise DomainError("This record has no customer account.")
        accounts_api.set_account_segment(session, automation, facts.account_id, action["value"])
    return f"{action['field']} set to {action['value']}"


def _already_ran(session: Session, rule: WorkflowRule, run_key: str) -> bool:
    return (
        session.scalar(
            select(WorkflowRun.id).where(
                WorkflowRun.tenant_id == rule.tenant_id,
                WorkflowRun.rule_id == rule.id,
                WorkflowRun.run_key == run_key,
            )
        )
        is not None
    )


def _runs_last_hour(session: Session, tenant_id: uuid.UUID, now: datetime) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.status == "done",
                WorkflowRun.created_at >= now - timedelta(hours=1),
            )
        )
        or 0
    )


def run_rule(
    session: Session,
    rule: WorkflowRule,
    *,
    record_type: str,
    record_id: uuid.UUID,
    run_key: str,
    depth: int,
    hourly_limit: int,
    now: datetime | None = None,
) -> str | None:
    """Check one rule against one record; act if its conditions match. Returns the run's
    status, or None when nothing was logged (already ran, record gone, conditions not met)."""
    now = now or datetime.now(UTC)
    if _already_ran(session, rule, run_key):
        return None
    automation = identity_api.automation_principal(session, rule.tenant_id)
    facts = _facts(session, automation, record_type, record_id)
    if facts is None or not rules.matches(rule.conditions, facts.values):
        return None
    run_id = uuid.uuid4()
    if depth >= MAX_DEPTH:
        status, message = "limited", "Stopped: started by other automatic steps (loop protection)."
    elif _runs_last_hour(session, rule.tenant_id, now) >= hourly_limit:
        status, message = (
            "limited",
            f"Stopped: the limit of {hourly_limit} automatic runs per hour was reached.",
        )
    else:
        try:
            with session.begin_nested(), caused_by_automation(depth + 1):
                done = [_do(session, automation, rule, facts, a, run_id, now) for a in rule.actions]
            status, message = "done", "; ".join(done)
        except (DomainError, PermanentJobError) as exc:
            status, message = "failed", str(getattr(exc, "detail", exc))
        except Exception as exc:  # noqa: BLE001 - one broken rule must not stop the others
            logger.exception("workflow rule failed", extra={"rule_id": str(rule.id)})
            status, message = "failed", f"Unexpected error ({type(exc).__name__})."
    session.execute(
        insert(WorkflowRun)
        .values(
            id=run_id,
            tenant_id=rule.tenant_id,
            rule_id=rule.id,
            run_key=run_key[:150],
            record_type=record_type,
            record_id=record_id,
            record_label=facts.label[:300],
            status=status,
            message=message[:500],
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "rule_id", "run_key"])
    )
    return status


def on_event(session: Session, event: Event, *, hourly_limit: int) -> None:
    key = catalogue.EVENT_RECORD_KEY.get(event.name)
    if key is None:
        return
    spec = catalogue.TRIGGERS[event.name]
    try:
        record_id = uuid.UUID(str(event.data[key]))
    except (KeyError, ValueError):
        return
    active = session.scalars(
        select(WorkflowRule).where(
            WorkflowRule.tenant_id == event.tenant_id,
            WorkflowRule.trigger == event.name,
            WorkflowRule.is_active.is_(True),
        )
    ).all()
    for rule in active:
        run_rule(
            session,
            rule,
            record_type=spec.record_type,
            record_id=record_id,
            run_key=f"event:{event.id}",
            depth=event.depth,
            hourly_limit=hourly_limit,
        )


def run_schedules(
    session: Session,
    now: datetime,
    *,
    hourly_limit: int,
    tenant_id: uuid.UUID | None = None,
) -> int:
    """Schedule triggers for one tenant (or all, for an explicit admin/test call)."""
    count = 0
    statement = select(WorkflowRule).where(
        WorkflowRule.is_active.is_(True), WorkflowRule.trigger.like("schedule.%")
    )
    if tenant_id is not None:
        statement = statement.where(WorkflowRule.tenant_id == tenant_id)
    rules_due = session.scalars(statement).all()
    for rule in rules_due:
        days = rule.days or 0
        if rule.trigger == "schedule.quote_expiring":
            candidates = [
                (qid, f"quote:{qid}")
                for qid in quotes_api.expiring_quote_ids(session, rule.tenant_id, now.date(), days)
            ]
        elif rule.trigger == "schedule.task_overdue":
            candidates = [
                (tid, f"task:{tid}:{due.date().isoformat()}")  # a new due date can fire again
                for tid, due in activities_api.overdue_tasks(session, rule.tenant_id, now, days)
            ]
        else:
            continue
        record_type = catalogue.TRIGGERS[rule.trigger].record_type
        for record_id, run_key in candidates:
            if run_rule(
                session,
                rule,
                record_type=record_type,
                record_id=record_id,
                run_key=run_key,
                depth=0,
                hourly_limit=hourly_limit,
                now=now,
            ):
                count += 1
    return count
