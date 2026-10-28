"""The fixed catalogue of actions an AI may propose (ADR 0014, decision 3).

Each kind says which records it works on, what its payload looks like (anything else is
refused), how to describe it to the approver, what to check when it is proposed, and which
owning module's api.py function performs it. New kinds are added here, with tests - never by a
model.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.records import LeadSnapshot
from app.modules.activities import api as activities_api
from app.modules.approvals.artifact import Change, Plan
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeadStatusPayload(_Payload):
    # "converted" only through the convert screen; never by an AI proposal.
    status: Literal["contacted", "qualified", "unqualified"]


class LeadAssignPayload(_Payload):
    owner_id: uuid.UUID


class TaskPayload(_Payload):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    due_in_days: Annotated[int, Field(ge=0, le=60)]
    # Empty = the person who asked for the proposal.
    assignee_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Proposal:
    """What the service knows when it checks or runs an action."""

    tenant_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    requested_by_user_id: uuid.UUID
    reason: str


# Returns an error text for the proposer (None = fine). Visibility is checked before.
Check = Callable[[Session, Proposal, Any], str | None]


@dataclass(frozen=True)
class Ran:
    """What running an action gives back: a short result for the history, and the id of the
    record it created, if any (so the outcome can be checked against the plan)."""

    text: str
    created_id: uuid.UUID | None = None


# Performs the action as the approver.
Run = Callable[[Session, Principal, Proposal, Any], Ran]
# The plan (ADR 0018): what the action will change, judged against the record as it is now.
Spec = Callable[[Session, Principal, Proposal, Any], Plan]
# What is true after the action ran, in the same shape as the plan's ``after`` values.
Observe = Callable[[Session, Principal, Proposal, Any, Ran], list[Change]]


@dataclass(frozen=True)
class ActionKind:
    name: str
    target_types: tuple[str, ...]
    payload: type[BaseModel]
    describe: Callable[[Any], str]
    check: Check
    run: Run
    spec: Spec
    observe: Observe


def _note(proposal: Proposal) -> str:
    return f"Approved AI proposal: {proposal.reason}"[:500]


def _no_check(session: Session, proposal: Proposal, payload: BaseModel) -> str | None:
    return None


def _run_status(
    session: Session, me: Principal, proposal: Proposal, payload: LeadStatusPayload
) -> Ran:
    leads_api.set_lead_status(session, me, proposal.target_id, payload.status, _note(proposal))
    return Ran(f"Lead status changed to {payload.status}.")


def _check_owner(session: Session, proposal: Proposal, payload: LeadAssignPayload) -> str | None:
    if not identity_api.is_assignable_sales_user(session, proposal.tenant_id, payload.owner_id):
        return "owner_id: must be an active sales person of the organisation"
    return None


def _run_assign(
    session: Session, me: Principal, proposal: Proposal, payload: LeadAssignPayload
) -> Ran:
    leads_api.assign_lead(session, me, proposal.target_id, payload.owner_id, _note(proposal))
    return Ran("Lead assigned.")


def _check_assignee(session: Session, proposal: Proposal, payload: TaskPayload) -> str | None:
    person = payload.assignee_id
    if person is not None and not identity_api.is_active_staff_member(
        session, proposal.tenant_id, person
    ):
        return "assignee_id: must be an active colleague"
    return None


def _run_task(session: Session, me: Principal, proposal: Proposal, payload: TaskPayload) -> Ran:
    link = {f"{proposal.target_type}_id": proposal.target_id}
    created = activities_api.create_task(
        session,
        me,
        subject=payload.subject,
        due_at=datetime.now(UTC) + timedelta(days=payload.due_in_days),
        assignee_id=payload.assignee_id or proposal.requested_by_user_id,
        lead_id=link.get("lead_id"),
        account_id=link.get("account_id"),
        contact_id=link.get("contact_id"),
    )
    return Ran("Task created.", created)


def _lead(session: Session, me: Principal, proposal: Proposal) -> LeadSnapshot:
    snapshot = leads_api.lead_snapshot(session, me, proposal.target_id)
    if snapshot is None:
        raise LookupError(
            "the lead cannot be read"
        )  # the Sentinel's caller turns this into a block
    return snapshot


def _basis(snapshot: LeadSnapshot) -> dict[str, Any]:
    return {
        "record_version": snapshot.version,
        "status": snapshot.status,
        "owner_id": str(snapshot.owner_id) if snapshot.owner_id else None,
    }


def _spec_status(
    session: Session, me: Principal, proposal: Proposal, payload: LeadStatusPayload
) -> Plan:
    lead = _lead(session, me, proposal)
    return Plan([Change("status", lead.status, payload.status)], _basis(lead))


def _observe_status(
    session: Session, me: Principal, proposal: Proposal, payload: LeadStatusPayload, ran: Ran
) -> list[Change]:
    return [Change("status", None, _lead(session, me, proposal).status)]


def _spec_assign(
    session: Session, me: Principal, proposal: Proposal, payload: LeadAssignPayload
) -> Plan:
    lead = _lead(session, me, proposal)
    return Plan([Change("owner_id", lead.owner_id, payload.owner_id)], _basis(lead))


def _observe_assign(
    session: Session, me: Principal, proposal: Proposal, payload: LeadAssignPayload, ran: Ran
) -> list[Change]:
    return [Change("owner_id", None, _lead(session, me, proposal).owner_id)]


def _spec_task(session: Session, me: Principal, proposal: Proposal, payload: TaskPayload) -> Plan:
    task = {
        "subject": payload.subject[:200],
        "due_in_days": payload.due_in_days,
        "assignee_id": str(payload.assignee_id or proposal.requested_by_user_id),
    }
    basis = _basis(_lead(session, me, proposal)) if proposal.target_type == "lead" else {}
    return Plan([Change("task", None, task)], basis)


def _observe_task(
    session: Session, me: Principal, proposal: Proposal, payload: TaskPayload, ran: Ran
) -> list[Change]:
    seen = None
    if ran.created_id is not None:
        seen = activities_api.task_snapshot(session, me, ran.created_id, datetime.now(UTC).date())
    return [Change("task", None, seen)]


def _describe_status(payload: LeadStatusPayload) -> str:
    return f"Change the lead's status to {payload.status}"


def _describe_task(payload: TaskPayload) -> str:
    return f"Plan a task: {payload.subject} (due in {payload.due_in_days} days)"


KINDS: dict[str, ActionKind] = {
    kind.name: kind
    for kind in (
        ActionKind(
            "lead.set_status",
            ("lead",),
            LeadStatusPayload,
            _describe_status,
            _no_check,
            _run_status,
            _spec_status,
            _observe_status,
        ),
        ActionKind(
            "lead.assign",
            ("lead",),
            LeadAssignPayload,
            lambda payload: "Give the lead to another sales person",
            _check_owner,
            _run_assign,
            _spec_assign,
            _observe_assign,
        ),
        ActionKind(
            "activity.create_task",
            ("lead", "account", "contact"),
            TaskPayload,
            _describe_task,
            _check_assignee,
            _run_task,
            _spec_task,
            _observe_task,
        ),
    )
}
