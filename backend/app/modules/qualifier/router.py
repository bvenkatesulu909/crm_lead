"""/api/v1/qualifier - the organisation's written lead-qualification procedure (QA1).

Thin layer: permissions, then the service; the write endpoints commit once. Tenant admins write,
sales managers and admins read, everyone else is refused.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.identity.api import require_any_permission
from app.modules.qualifier import assess, rules, service
from app.modules.qualifier.llm import model_for
from app.modules.qualifier.models import LeadAssessment, QualificationProcedure
from app.modules.qualifier.schemas import (
    AssessmentCreate,
    AssessmentPage,
    AssessmentRead,
    ProcedureDeactivate,
    ProcedurePage,
    ProcedureRead,
    ProcedureSave,
    TryRead,
    TryRequest,
)

router = APIRouter(prefix="/qualifier", tags=["qualifier"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.QUALIFIER_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.QUALIFIER_MANAGE))]
Runner = Annotated[Principal, Depends(require_any_permission(Permission.QUALIFIER_RUN))]


def qualifier_model(request: Request) -> ChatModel:
    """The model behind the Qualifier. Tests put a scripted one on the app."""
    override: ChatModel | None = getattr(request.app.state, "qualifier_model", None)
    return override or model_for(request.app.state.settings)


Model = Annotated[ChatModel, Depends(qualifier_model)]


def _read(procedure: QualificationProcedure) -> ProcedureRead:
    return ProcedureRead(
        id=procedure.id,
        version=procedure.version,
        name=procedure.name,
        steps=list(procedure.steps),
        cleaned=[str(code) for code in procedure.cleaned],
        active=procedure.active,
        retired_at=procedure.retired_at,
        created_by_user_id=procedure.created_by_user_id,
        created_at=procedure.created_at,
    )


@router.get(
    "/procedure",
    summary="The active qualification procedure of your organisation",
    responses=problem_responses(401, 403, 404),
)
def get_procedure(principal: Reader, session: Db) -> ProcedureRead:
    return _read(service.get_active(session, principal))


@router.get(
    "/procedure/versions",
    summary="Every saved version of the procedure, newest first",
    responses=problem_responses(401, 403),
)
def list_versions(
    principal: Reader,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProcedurePage:
    items, total = service.list_versions(session, principal, limit=limit, offset=offset)
    return ProcedurePage(items=[_read(i) for i in items], total=total, limit=limit, offset=offset)


@router.put(
    "/procedure",
    status_code=201,
    summary="Save the procedure as a new version (the previous one is kept in the history)",
    description="Links, addresses, markup and hidden characters are removed from the steps; a "
    "step that reads like an instruction to an AI is refused. Send `replaces_version` (the "
    "active version you edited) so two people cannot overwrite each other.",
    responses=problem_responses(401, 403, 409, 422),
)
def save_procedure(data: ProcedureSave, principal: Manager, session: Db) -> ProcedureRead:
    procedure = service.save_procedure(
        session,
        principal,
        name=data.name,
        steps=data.steps,
        replaces_version=data.replaces_version,
    )
    session.commit()
    return _read(procedure)


@router.post(
    "/procedure/deactivate",
    summary="Switch the procedure off; the Qualifier then does nothing until one is saved",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def deactivate_procedure(
    data: ProcedureDeactivate, principal: Manager, session: Db
) -> ProcedureRead:
    procedure = service.deactivate(session, principal, version=data.version)
    session.commit()
    return _read(procedure)


def _read_assessment(record: LeadAssessment, blocked_message: str | None = None) -> AssessmentRead:
    return AssessmentRead(
        id=record.id,
        lead_id=record.lead_id,
        procedure_version=record.procedure_version,
        decision=record.decision,
        matched_steps=[int(n) for n in record.matched_steps],
        reasons=[str(r) for r in record.reasons],
        missing=[str(m) for m in record.missing],
        outcome=record.outcome,
        proposal_id=record.proposal_id,
        proposal_link=f"/approvals/{record.proposal_id}" if record.proposal_id else None,
        requested_by_user_id=record.requested_by_user_id,
        created_at=record.created_at,
        blocked_message=blocked_message,
    )


@router.post(
    "/assessments",
    status_code=201,
    summary="Ask the Qualifier to assess one lead; it suggests, a different person decides",
    description="Needs a written procedure and a lead you may read. The result may be a proposal "
    "in the approval queue (nothing changes until a different person approves it) or just a "
    "recorded assessment. Off, over budget or over a limit: 503 / 429 with nothing proposed.",
    responses=problem_responses(401, 403, 404, 422, 429, 503),
)
def create_assessment(
    data: AssessmentCreate, principal: Runner, session: Db, request: Request, model: Model
) -> AssessmentRead:
    settings: Settings = request.app.state.settings
    try:
        result = assess.assess_lead(
            session,
            principal,
            model,
            data.lead_id,
            limits=assess.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except assess.AssessmentInvalidError:
        session.commit()  # the model was called: keep the tokens it used on the month's total
        raise
    session.commit()
    return _read_assessment(result.assessment, result.blocked_message)


@router.get(
    "/assessments",
    summary="The assessments of one lead, newest first",
    responses=problem_responses(401, 403, 404),
)
def list_assessments(
    lead_id: uuid.UUID,
    principal: Runner,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AssessmentPage:
    items, total = assess.assessments_for_lead(
        session, principal, lead_id, limit=limit, offset=offset
    )
    return AssessmentPage(
        items=[_read_assessment(i) for i in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "/procedure/try",
    summary="Dry run for an administrator: assess one lead and show the result, nothing else",
    description="Uses the active steps, or the draft `steps` you send. No proposal, no record, "
    "no audit entry; the model call still counts against the agent's token budget.",
    responses=problem_responses(401, 403, 404, 422, 503),
)
def try_procedure(
    data: TryRequest, principal: Manager, session: Db, request: Request, model: Model
) -> TryRead:
    settings: Settings = request.app.state.settings
    try:
        run = assess.try_procedure(
            session,
            principal,
            model,
            data.lead_id,
            steps=data.steps,
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except assess.AssessmentInvalidError:
        session.commit()  # keep the tokens the model used
        raise
    session.commit()
    return TryRead(
        decision=run.assessment.decision,
        matched_steps=run.assessment.matched_steps,
        reasons=run.assessment.reasons,
        missing=run.assessment.missing,
        would_propose=rules.summary(run.planned) if run.planned else None,
        procedure_version=run.procedure_version,
    )
