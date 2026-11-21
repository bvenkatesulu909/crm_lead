"""/api/v1/call-notes and /api/v1/leads/{lead}/calls/{call}/notes - call notes and the deal
checklist (ADR 0035, CN3).

Thin layer: the coarse permission, then the service (which also checks that the person may read the
lead - else 404). The write endpoints commit once. Switching the feature on is the AI agents
registry's business (`PATCH /api/v1/agents/call_notes`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.call_notes import proposals, rules, service
from app.modules.call_notes.llm import model_for
from app.modules.call_notes.models import CallNote
from app.modules.call_notes.schemas import (
    FieldRead,
    FrameworkRead,
    LineRead,
    NotesPage,
    NotesRead,
    PlannedMemoryRead,
    PlannedTaskRead,
    ProposalOutcomeRead,
    ProposalPreviewRead,
    ProposalRequest,
    ProposalsRead,
    SettingsRead,
    SettingsUpdate,
    VersionRead,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/call-notes", tags=["call-notes"])
notes_router = APIRouter(prefix="/leads", tags=["call-notes"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.CALL_NOTES_RUN, Permission.CALL_NOTES_MANAGE)),
]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.CALL_NOTES_MANAGE))]
Runner = Annotated[Principal, Depends(require_any_permission(Permission.CALL_NOTES_RUN))]


def call_notes_model(request: Request) -> ChatModel:
    """The model behind call notes. Tests put a scripted one on the app."""
    override: ChatModel | None = getattr(request.app.state, "call_notes_model", None)
    return override or model_for(request.app.state.settings)


Model = Annotated[ChatModel, Depends(call_notes_model)]


def _settings_read(view: service.SettingsView) -> SettingsRead:
    return SettingsRead(
        framework=view.framework,
        version=view.version,
        frameworks=[
            FrameworkRead(
                key=name,
                title=rules.TITLES[name],
                fields=[FieldRead(key=f.key, label=f.label, hint=f.hint) for f in fields],
            )
            for name, fields in rules.FRAMEWORKS.items()
        ],
    )


def _notes_read(result: service.NotesResult) -> NotesRead:
    note = result.note
    return NotesRead(
        id=note.id,
        version_no=note.version_no,
        framework=note.framework,
        requested_by_user_id=note.requested_by_user_id,
        model_name=note.model_name,
        downgraded=note.downgraded,
        dropped_notes=note.dropped_notes,
        cleaned_codes=[str(code) for code in note.cleaned_codes],
        created_at=note.created_at,
        lines=[
            LineRead(
                position=line.position,
                field=line.field,
                label=rules.LABELS.get(line.field, line.field),
                state=line.state,
                value=line.value,
                quote=line.quote,
                start_ms=line.start_ms,
                end_ms=line.end_ms,
                reason=line.reason,
                note_code=line.note_code,
            )
            for line in result.lines
        ],
    )


def _version_read(note: CallNote) -> VersionRead:
    return VersionRead(
        version_no=note.version_no,
        framework=note.framework,
        requested_by_user_id=note.requested_by_user_id,
        created_at=note.created_at,
    )


@router.get(
    "/settings",
    summary="The checklist frame of your organisation (BANT or MEDDIC) and the fields of each",
    responses=problem_responses(401, 403),
)
def get_settings(principal: Reader, session: Db) -> SettingsRead:
    return _settings_read(service.get_settings(session, principal))


@router.put(
    "/settings",
    summary="Choose the checklist frame (administrators only)",
    description="Send the version you last saw (0 or nothing before the first choice). A stale "
    "version is a 409. Saving the frame already chosen changes nothing.",
    responses=problem_responses(401, 403, 409, 422),
)
def put_settings(data: SettingsUpdate, principal: Manager, session: Db) -> SettingsRead:
    view = service.set_framework(session, principal, data.framework, data.version)
    session.commit()
    return _settings_read(view)


@notes_router.post(
    "/{lead_id}/calls/{call_id}/notes",
    status_code=201,
    summary="Draft call notes and a deal checklist from the transcript of one call",
    description="No body: the lead and call are in the address and the frame is your "
    "organisation's. The call must belong to a lead you may read and have a finished transcript. "
    "The result is a DRAFT: nothing in the CRM changes. Off, over budget or over a limit: 503 / "
    "429. An answer that cannot be verified: 422.",
    responses=problem_responses(401, 403, 404, 409, 422, 429, 503),
)
def create_notes(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    principal: Runner,
    session: Db,
    request: Request,
    model: Model,
) -> NotesRead:
    settings: Settings = request.app.state.settings
    try:
        result = service.run_notes(
            session,
            principal,
            model,
            lead_id,
            call_id,
            model_name=settings.ai_provider,
            limits=service.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except service.NotesRefusedError:
        session.commit()  # keep the tokens the model used
        raise
    session.commit()
    return _notes_read(result)


@notes_router.get(
    "/{lead_id}/calls/{call_id}/notes",
    summary="The newest call notes of a call and the list of earlier versions",
    responses=problem_responses(401, 403, 404, 409),
)
def list_notes(lead_id: uuid.UUID, call_id: uuid.UUID, principal: Runner, session: Db) -> NotesPage:
    newest, versions = service.newest_and_versions(session, principal, lead_id, call_id)
    return NotesPage(
        newest=_notes_read(newest) if newest else None,
        versions=[_version_read(v) for v in versions],
    )


@notes_router.get(
    "/{lead_id}/calls/{call_id}/notes/{version_no}",
    summary="One version of the call notes of a call",
    responses=problem_responses(401, 403, 404, 409),
)
def get_notes(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    version_no: Annotated[int, Path(ge=1)],
    principal: Runner,
    session: Db,
) -> NotesRead:
    return _notes_read(service.read_version(session, principal, lead_id, call_id, version_no))


@notes_router.get(
    "/{lead_id}/calls/{call_id}/notes/{version_no}/proposals/preview",
    summary="What asking for proposals from a draft would suggest (stores nothing)",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def preview_proposals(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    version_no: Annotated[int, Path(ge=1)],
    principal: Runner,
    session: Db,
    positions: Annotated[list[int] | None, Query(max_length=20)] = None,
    follow_up_task: bool = True,
) -> ProposalPreviewRead:
    plan = proposals.preview(
        session,
        principal,
        lead_id,
        call_id,
        version_no,
        positions=positions,
        follow_up_task=follow_up_task,
    )
    return ProposalPreviewRead(
        memory=[
            PlannedMemoryRead(
                position=item.position,
                field=item.field,
                label=item.label,
                key=item.key,
                value=item.value,
                note=item.note,
            )
            for item in plan.memory
        ],
        task=(
            PlannedTaskRead(subject=plan.task.subject, due_in_days=plan.task.due_in_days)
            if plan.task
            else None
        ),
    )


@notes_router.post(
    "/{lead_id}/calls/{call_id}/notes/{version_no}/proposals",
    status_code=201,
    summary="Turn a draft into proposals; a different person decides",
    description="Each chosen line becomes a proposal to note a detail in the buyer memory - always "
    "as an ASSUMPTION, never a fact - and the unknown lines can become one follow-up task. Nothing "
    "changes until a different person approves. A line the safety check refuses or that is already "
    "confirmed is reported, not an error.",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def create_proposals(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    version_no: Annotated[int, Path(ge=1)],
    data: ProposalRequest,
    principal: Runner,
    session: Db,
) -> ProposalsRead:
    done = proposals.propose(
        session,
        principal,
        lead_id,
        call_id,
        version_no,
        positions=data.positions,
        follow_up_task=data.follow_up_task,
    )
    session.commit()
    return ProposalsRead(
        items=[
            ProposalOutcomeRead(
                target=o.target,
                position=o.position,
                status=o.status,
                proposal_id=o.proposal_id,
                proposal_link=f"/approvals/{o.proposal_id}" if o.proposal_id else None,
                message=o.message,
            )
            for o in done.outcomes
        ]
    )
