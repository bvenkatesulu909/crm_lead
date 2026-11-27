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

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.records import LeadSnapshot
from app.modules.activities import api as activities_api
from app.modules.approvals.artifact import Change, Plan
from app.modules.buyer_memory import api as buyer_memory_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.proposal_decks import api as proposal_decks_api
from app.modules.video_brief import api as video_brief_api


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


class DeckSummaryPayload(_Payload):
    """The text of a quote deck's "why this proposal" slide (ADR 0032 Amendment A, PD7)."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class VideoScriptPayload(_Payload):
    """A drafted script for a lead's buyer video (ADR 0041, VB5): the choices it was written for
    and the lines. Nothing else; the lead is the target."""

    language: Literal["en", "hi", "te"]
    tone: Literal["warm", "professional", "brisk"]
    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"]
    length_seconds: Literal[30, 60, 90]
    lines: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=300)]],
        Field(min_length=1, max_length=12),
    ]


class BuyerMemoryAssumptionPayload(_Payload):
    """One detail for a lead's buyer memory, always recorded as an ASSUMPTION (ADR 0035, CN4).
    ``note`` says where it came from (the call and the moment); ``call_id`` and ``at_ms`` point
    at it. A fact needs a person to confirm it with the buyer's words, so this kind has no
    status."""

    key: str
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    call_id: uuid.UUID
    at_ms: Annotated[int, Field(ge=0, le=86_400_000)]

    @field_validator("key")
    @classmethod
    def _known_key(cls, key: str) -> str:
        if key not in {name for name, _label in buyer_memory_api.KEYS}:
            raise ValueError("must be one of the twelve buyer memory keys")
        return key

    @field_validator("value", "note")
    @classmethod
    def _one_line(cls, text: str) -> str:
        # The stored text is cleaned the same way, so the plan and the outcome compare equal.
        return " ".join(text.split())


@dataclass(frozen=True)
class Proposal:
    """What the service knows when it checks or runs an action."""

    tenant_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    requested_by_user_id: uuid.UUID
    reason: str
    # Known once the proposal is stored (it is not yet when the proposal is checked).
    action_id: uuid.UUID | None = None


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
        opportunity_id=link.get("opportunity_id"),
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


def _check_summary(session: Session, proposal: Proposal, payload: DeckSummaryPayload) -> str | None:
    return proposal_decks_api.summary_problem(
        session, proposal.tenant_id, proposal.target_id, payload.text
    )


def _run_summary(
    session: Session, me: Principal, proposal: Proposal, payload: DeckSummaryPayload
) -> Ran:
    if me.user_id is None:
        raise LookupError("only a person can approve")
    summary_id = proposal_decks_api.add_summary(
        session,
        proposal.tenant_id,
        proposal.target_id,
        payload.text,
        me.user_id,
        proposal.action_id,
    )
    return Ran("Deck summary slide saved.", summary_id)


def _spec_summary(
    session: Session, me: Principal, proposal: Proposal, payload: DeckSummaryPayload
) -> Plan:
    current = proposal_decks_api.latest_summary(session, proposal.tenant_id, proposal.target_id)
    return Plan(
        [Change("deck_summary", current, payload.text)], {"quote_id": str(proposal.target_id)}
    )


def _observe_summary(
    session: Session, me: Principal, proposal: Proposal, payload: DeckSummaryPayload, ran: Ran
) -> list[Change]:
    now = proposal_decks_api.latest_summary(session, proposal.tenant_id, proposal.target_id)
    return [Change("deck_summary", None, now)]


def _check_script(session: Session, proposal: Proposal, payload: VideoScriptPayload) -> str | None:
    return video_brief_api.script_problem(payload.lines, payload.length_seconds)


def _run_script(
    session: Session, me: Principal, proposal: Proposal, payload: VideoScriptPayload
) -> Ran:
    if proposal.action_id is None:
        raise LookupError("a script is saved only from a stored proposal")
    script_id = video_brief_api.add_approved_script(
        session,
        me,
        proposal.target_id,
        language=payload.language,
        tone=payload.tone,
        goal=payload.goal,
        length_seconds=payload.length_seconds,
        lines=payload.lines,
        proposal_id=proposal.action_id,
    )
    return Ran("Video script saved.", script_id)


def _spec_script(
    session: Session, me: Principal, proposal: Proposal, payload: VideoScriptPayload
) -> Plan:
    now = video_brief_api.latest_script_lines(session, proposal.tenant_id, proposal.target_id)
    return Plan(
        [Change("video_script", now, list(payload.lines))], {"lead_id": str(proposal.target_id)}
    )


def _observe_script(
    session: Session, me: Principal, proposal: Proposal, payload: VideoScriptPayload, ran: Ran
) -> list[Change]:
    now = video_brief_api.latest_script_lines(session, proposal.tenant_id, proposal.target_id)
    return [Change("video_script", None, now)]


def _check_memory(
    session: Session, proposal: Proposal, payload: BuyerMemoryAssumptionPayload
) -> str | None:
    return buyer_memory_api.assumption_problem(
        session, proposal.tenant_id, proposal.target_id, payload.key, payload.value
    )


def _run_memory(
    session: Session, me: Principal, proposal: Proposal, payload: BuyerMemoryAssumptionPayload
) -> Ran:
    stored = buyer_memory_api.add_assumption(
        session,
        me,
        proposal.target_id,
        key=payload.key,
        value=payload.value,
        reason=payload.note,
    )
    return Ran("Recorded in the buyer memory as an assumption.", stored.id)


def _spec_memory(
    session: Session, me: Principal, proposal: Proposal, payload: BuyerMemoryAssumptionPayload
) -> Plan:
    now = buyer_memory_api.current_text(
        session, proposal.tenant_id, proposal.target_id, payload.key
    )
    return Plan(
        [Change(f"buyer_memory.{payload.key}", now, payload.value)],
        {"lead_id": str(proposal.target_id), "call_id": str(payload.call_id)},
    )


def _observe_memory(
    session: Session,
    me: Principal,
    proposal: Proposal,
    payload: BuyerMemoryAssumptionPayload,
    ran: Ran,
) -> list[Change]:
    now = buyer_memory_api.current_text(
        session, proposal.tenant_id, proposal.target_id, payload.key
    )
    return [Change(f"buyer_memory.{payload.key}", None, now)]


def _describe_memory(payload: BuyerMemoryAssumptionPayload) -> str:
    labels = dict(buyer_memory_api.KEYS)
    return (
        "Note in the buyer memory, as an assumption (not a fact): "
        f"{labels.get(payload.key, payload.key)}: {payload.value}"
    )


def _describe_status(payload: LeadStatusPayload) -> str:
    return f"Change the lead's status to {payload.status}"


def _describe_task(payload: TaskPayload) -> str:
    return f"Plan a task: {payload.subject} (due in {payload.due_in_days} days)"


# --- a callback the website visitor asked for (ADR 0038, VR3) ---------------------------------

CALLBACK_DAYS = {"today": 0, "tomorrow": 1, "day_after": 2}
CALLBACK_WINDOWS = ("morning", "afternoon", "evening")
CALLBACK_LANGUAGES = {"en": "English", "hi": "Hindi", "te": "Telugu"}


class CallbackPayload(_Payload):
    """Only fixed words: nothing the visitor or the model typed ends up in the task."""

    day: Literal["today", "tomorrow", "day_after"]
    window: Literal["morning", "afternoon", "evening"]
    language: Literal["en", "hi", "te"]


def callback_subject(payload: CallbackPayload) -> str:
    day = payload.day.replace("_", " ")
    day = "the day after tomorrow" if payload.day == "day_after" else day
    return (
        f"Call back the website visitor {day} in the {payload.window}, "
        f"in {CALLBACK_LANGUAGES[payload.language]}"
    )


def _describe_callback(payload: CallbackPayload) -> str:
    return "Call the website visitor back: " + callback_subject(payload).split("visitor ", 1)[1]


def _callback_owner(session: Session, me: Principal, proposal: Proposal) -> uuid.UUID:
    """The lead's owner, else the person who approves (a manager, who can hand it on)."""
    snapshot = leads_api.lead_snapshot(session, me, proposal.target_id)
    if snapshot is not None and snapshot.owner_id is not None:
        return snapshot.owner_id
    if me.user_id is None:
        raise LookupError("only a person can approve")
    return me.user_id


def _run_callback(
    session: Session, me: Principal, proposal: Proposal, payload: CallbackPayload
) -> Ran:
    created = activities_api.create_task(
        session,
        me,
        subject=callback_subject(payload),
        due_at=datetime.now(UTC) + timedelta(days=CALLBACK_DAYS[payload.day]),
        assignee_id=_callback_owner(session, me, proposal),
        lead_id=proposal.target_id,
        account_id=None,
        contact_id=None,
        opportunity_id=None,
    )
    return Ran("Callback task created.", created)


def _spec_callback(
    session: Session, me: Principal, proposal: Proposal, payload: CallbackPayload
) -> Plan:
    task = {
        "subject": callback_subject(payload),
        "due_in_days": CALLBACK_DAYS[payload.day],
        "assignee_id": str(_callback_owner(session, me, proposal)),
    }
    return Plan([Change("task", None, task)], _basis(_lead(session, me, proposal)))


def _observe_callback(
    session: Session, me: Principal, proposal: Proposal, payload: CallbackPayload, ran: Ran
) -> list[Change]:
    seen = None
    if ran.created_id is not None:
        seen = activities_api.task_snapshot(session, me, ran.created_id, datetime.now(UTC).date())
    return [Change("task", None, seen)]


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
            ("lead", "account", "contact", "opportunity"),
            TaskPayload,
            _describe_task,
            _check_assignee,
            _run_task,
            _spec_task,
            _observe_task,
        ),
        ActionKind(
            "lead.request_callback",
            ("lead",),
            CallbackPayload,
            _describe_callback,
            _no_check,
            _run_callback,
            _spec_callback,
            _observe_callback,
        ),
        ActionKind(
            "buyer_memory.add_assumption",
            ("lead",),
            BuyerMemoryAssumptionPayload,
            _describe_memory,
            _check_memory,
            _run_memory,
            _spec_memory,
            _observe_memory,
        ),
        ActionKind(
            "lead.video_script",
            ("lead",),
            VideoScriptPayload,
            lambda payload: (
                "Save a drafted script for this buyer's video (nothing is sent to the buyer)"
            ),
            _check_script,
            _run_script,
            _spec_script,
            _observe_script,
        ),
        ActionKind(
            "quote.deck_summary",
            ("quote",),
            DeckSummaryPayload,
            lambda payload: 'Add a "Why this proposal" slide to the quote\'s proposal deck',
            _check_summary,
            _run_summary,
            _spec_summary,
            _observe_summary,
        ),
    )
}
