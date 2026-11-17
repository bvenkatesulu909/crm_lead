"""Turning a call-notes draft into proposals for the approval queue (ADR 0035, CN4).

    permission ─► the draft (only of a call whose lead the asker may read) ─► the plan (pure) ─►
    one proposal per line through the approvals module and its Sentinel

Nothing changes in the CRM: every proposal waits for a DIFFERENT person to approve it, and the
buyer-memory kind can only ever record an assumption. A refused or duplicate proposal is reported
per line; it never stops the others (except when the person already has too many waiting). No model
is called here. Services never commit.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.modules.approvals import api as approvals_api
from app.modules.call_notes import proposal_rules as plan_rules
from app.modules.call_notes import repository, service
from app.modules.call_notes.models import CallNote

AGENT = "call_notes"
MEMORY_KIND = "buyer_memory.add_assumption"
TASK_KIND = "activity.create_task"


class PlanRefusedError(service.NotesRefusedError):
    """The request cannot be turned into proposals (a line that cannot be proposed...)."""


@dataclass(frozen=True)
class Outcome:
    target: str  # a buyer-memory key, or "task"
    position: int | None
    status: str  # proposed, blocked, refused, skipped
    proposal_id: uuid.UUID | None = None
    message: str | None = None


@dataclass(frozen=True)
class Done:
    outcomes: list[Outcome] = field(default_factory=list)


def _load(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    version_no: int,
) -> tuple[CallNote, list[plan_rules.StoredLine]]:
    note = service.load_version(session, principal, lead_id, call_id, version_no)
    lines = [
        plan_rules.StoredLine(
            ln.position, ln.field, ln.state, ln.value, ln.quote, ln.start_ms, ln.reason
        )
        for ln in repository.lines_of(session, note.tenant_id, note.id)
    ]
    return note, lines


def _plan(
    note: CallNote,
    lines: list[plan_rules.StoredLine],
    positions: list[int] | None,
    follow_up_task: bool,
) -> plan_rules.Plan:
    try:
        return plan_rules.plan(
            note.framework,
            lines,
            version_no=note.version_no,
            positions=positions,
            follow_up_task=follow_up_task,
        )
    except plan_rules.PlanRefused as refusal:
        raise PlanRefusedError(refusal.code, str(refusal)) from None


def preview(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    version_no: int,
    *,
    positions: list[int] | None,
    follow_up_task: bool,
) -> plan_rules.Plan:
    """What asking for proposals would suggest, in plain words. Stores nothing."""
    note, lines = _load(session, principal, lead_id, call_id, version_no)
    return _plan(note, lines, positions, follow_up_task)


def _one(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    *,
    target: str,
    position: int | None,
    kind: str,
    payload: dict[str, Any],
    reason: str,
) -> Outcome:
    try:
        # A savepoint: a refused proposal leaves nothing behind.
        with session.begin_nested():
            action = approvals_api.propose(
                session,
                principal,
                kind=kind,
                target_type="lead",
                target_id=lead_id,
                payload=payload,
                reason=reason,
                agent=AGENT,
            )
    except approvals_api.ProposalBlockedError as refusal:
        # Outside the savepoint, so the audit entry of the refusal stays with the request.
        approvals_api.audit_blocked(session, principal, refusal)
        return Outcome(target, position, "blocked", message=refusal.detail)
    except approvals_api.InvalidActionError as refusal:
        return Outcome(target, position, "refused", message=refusal.detail)
    return Outcome(target, position, "proposed", proposal_id=action.id)


def propose(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    version_no: int,
    *,
    positions: list[int] | None,
    follow_up_task: bool,
) -> Done:
    """Make the proposals for a draft. The result says what happened to each one."""
    note, lines = _load(session, principal, lead_id, call_id, version_no)
    chosen = _plan(note, lines, positions, follow_up_task)
    todo: list[tuple[str, int | None, str, dict[str, Any], str]] = [
        (
            item.key,
            item.position,
            MEMORY_KIND,
            {
                "key": item.key,
                "value": item.value,
                "note": item.note,
                "call_id": str(call_id),
                "at_ms": item.at_ms,
            },
            item.reason,
        )
        for item in chosen.memory
    ]
    if chosen.task is not None:
        todo.append(
            (
                "task",
                None,
                TASK_KIND,
                {"subject": chosen.task.subject, "due_in_days": chosen.task.due_in_days},
                chosen.task.reason,
            )
        )
    outcomes: list[Outcome] = []
    full = False
    for target, position, kind, payload, reason in todo:
        if full:
            outcomes.append(
                Outcome(target, position, "skipped", message="Too many proposals are waiting.")
            )
            continue
        try:
            outcomes.append(
                _one(
                    session,
                    principal,
                    lead_id,
                    target=target,
                    position=position,
                    kind=kind,
                    payload=payload,
                    reason=reason,
                )
            )
        except approvals_api.LimitReachedError as limit:
            full = True
            outcomes.append(Outcome(target, position, "skipped", message=limit.detail))
    counts = {
        status: sum(1 for o in outcomes if o.status == status)
        for status in ("proposed", "blocked", "refused", "skipped")
    }
    # Ids and counts only - never a quote, a value or a reason.
    record_audit(
        session,
        principal,
        action="call_notes.proposed",
        entity_type="call_note",
        entity_id=note.id,
        changes={
            "recording_id": str(call_id),
            "lead_id": str(lead_id),
            "version_no": version_no,
            "counts": counts,
            "proposal_ids": [str(o.proposal_id) for o in outcomes if o.proposal_id],
        },
    )
    return Done(outcomes)
