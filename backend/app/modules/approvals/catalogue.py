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
from app.modules.activities import api as activities_api
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
# Performs the action as the approver; returns a short result for the history.
Run = Callable[[Session, Principal, Proposal, Any], str]


@dataclass(frozen=True)
class ActionKind:
    name: str
    target_types: tuple[str, ...]
    payload: type[BaseModel]
    describe: Callable[[Any], str]
    check: Check
    run: Run


def _note(proposal: Proposal) -> str:
    return f"Approved AI proposal: {proposal.reason}"[:500]


def _no_check(session: Session, proposal: Proposal, payload: BaseModel) -> str | None:
    return None


def _run_status(
    session: Session, me: Principal, proposal: Proposal, payload: LeadStatusPayload
) -> str:
    leads_api.set_lead_status(session, me, proposal.target_id, payload.status, _note(proposal))
    return f"Lead status changed to {payload.status}."


def _check_owner(session: Session, proposal: Proposal, payload: LeadAssignPayload) -> str | None:
    if not identity_api.is_assignable_sales_user(session, proposal.tenant_id, payload.owner_id):
        return "owner_id: must be an active sales person of the organisation"
    return None


def _run_assign(
    session: Session, me: Principal, proposal: Proposal, payload: LeadAssignPayload
) -> str:
    leads_api.assign_lead(session, me, proposal.target_id, payload.owner_id, _note(proposal))
    return "Lead assigned."


def _check_assignee(session: Session, proposal: Proposal, payload: TaskPayload) -> str | None:
    person = payload.assignee_id
    if person is not None and not identity_api.is_active_staff_member(
        session, proposal.tenant_id, person
    ):
        return "assignee_id: must be an active colleague"
    return None


def _run_task(session: Session, me: Principal, proposal: Proposal, payload: TaskPayload) -> str:
    link = {f"{proposal.target_type}_id": proposal.target_id}
    activities_api.create_task(
        session,
        me,
        subject=payload.subject,
        due_at=datetime.now(UTC) + timedelta(days=payload.due_in_days),
        assignee_id=payload.assignee_id or proposal.requested_by_user_id,
        lead_id=link.get("lead_id"),
        account_id=link.get("account_id"),
        contact_id=link.get("contact_id"),
    )
    return "Task created."


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
        ),
        ActionKind(
            "lead.assign",
            ("lead",),
            LeadAssignPayload,
            lambda payload: "Give the lead to another sales person",
            _check_owner,
            _run_assign,
        ),
        ActionKind(
            "activity.create_task",
            ("lead", "account", "contact"),
            TaskPayload,
            _describe_task,
            _check_assignee,
            _run_task,
        ),
    )
}
