"""/api/v1/deal-risk - the deal risk forecast (ADR 0037, DR3).

Thin layer: permission (sales managers and administrators), then the service; it commits once.
The risk is worked out by code from the CRM's own records. Only the optional coach (DR5) asks a
model, and it only writes advice and suggests tasks that wait in the approval queue.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.deal_risk import coach, service
from app.modules.deal_risk.coach_llm import coach_model_for
from app.modules.deal_risk.models import DealRiskSnapshot
from app.modules.deal_risk.schemas import (
    DealRiskAdviceLine,
    DealRiskCoachRead,
    DealRiskDealRead,
    DealRiskList,
    DealRiskProposalRef,
    DealRiskRead,
    DealRiskSnapshotList,
    DealRiskSnapshotRead,
)
from app.modules.identity.api import require_any_permission
from app.modules.sales import api as sales_api

router = APIRouter(prefix="/deal-risk", tags=["deal-risk"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.DEAL_RISK_READ))]


def _snapshot(row: DealRiskSnapshot) -> DealRiskSnapshotRead:
    return DealRiskSnapshotRead.model_validate(
        {
            "id": row.id,
            "opportunity_id": row.opportunity_id,
            "level": row.level,
            "score": row.score,
            "rules_version": row.rules_version,
            "source": row.source,
            "computed_at": row.created_at,
            "factors": row.factors,
            "unknown": row.unknown,
        }
    )


def _with_deal(row: DealRiskSnapshot, deal: sales_api.DealLabel | None) -> DealRiskRead:
    return DealRiskRead(
        **_snapshot(row).model_dump(),
        deal=DealRiskDealRead(
            id=deal.id,
            name=deal.name,
            account_id=deal.account_id,
            stage=deal.stage,
            amount=deal.amount,
            currency=deal.currency,
        )
        if deal
        else None,
    )


@router.get(
    "",
    summary="The newest forecast of every open deal you may read, highest risk first",
    description="A forecast is an estimate from the listed reasons, not a promise and not a "
    "probability. Only deals you may read appear; filtering happens in the database.",
    responses=problem_responses(401, 403),
)
def list_risk(
    principal: Reader,
    session: Db,
    level: Annotated[Literal["low", "medium", "high"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DealRiskList:
    rows, total, labels = service.list_latest(
        session, principal, level=level, limit=limit, offset=offset
    )
    return DealRiskList(
        items=[_with_deal(r, labels.get(r.opportunity_id)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{opportunity_id}",
    summary="The newest stored forecast of one deal",
    description="404 for a deal you may not read or a made-up id; `deal_risk_not_computed` "
    "(also 404) when none has been stored yet - ask for one with POST .../recompute.",
    responses=problem_responses(401, 403, 404),
)
def get_risk(opportunity_id: uuid.UUID, principal: Reader, session: Db) -> DealRiskRead:
    row = service.latest_snapshot(session, principal, opportunity_id)
    if row is None:
        raise service.NotComputedError
    labels = sales_api.deal_labels(session, principal, [opportunity_id])
    return _with_deal(row, labels.get(opportunity_id))


@router.get(
    "/{opportunity_id}/history",
    summary="Earlier forecasts of one deal, newest first (what changed)",
    responses=problem_responses(401, 403, 404),
)
def get_history(
    opportunity_id: uuid.UUID,
    principal: Reader,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> DealRiskSnapshotList:
    rows = service.history(session, principal, opportunity_id, limit)
    return DealRiskSnapshotList(items=[_snapshot(r) for r in rows])


@router.post(
    "/{opportunity_id}/recompute",
    status_code=201,
    summary="Work the forecast out now and store it",
    description="Uses the CRM's records as you may read them. At most "
    "`CRM_DEAL_RISK_RECOMPUTE_PER_USER_HOUR` (30) per person per hour: 429 beyond that. A closed "
    "deal, a deal you may not read or a made-up id answers 404. Nothing is sent to a model.",
    responses=problem_responses(401, 403, 404, 429),
)
def recompute(
    opportunity_id: uuid.UUID, principal: Reader, session: Db, request: Request
) -> DealRiskRead:
    settings: Settings = request.app.state.settings
    row = service.snapshot_on_demand(
        session,
        principal,
        opportunity_id,
        datetime.now(UTC),
        per_user_hour=service.per_user_hour(settings),
    )
    session.commit()
    labels = sales_api.deal_labels(session, principal, [opportunity_id])
    return _with_deal(row, labels.get(opportunity_id))


def coach_model(request: Request) -> ChatModel:
    """The model behind the coach. Tests put a scripted one on the app."""
    override: ChatModel | None = getattr(request.app.state, "deal_risk_coach_model", None)
    return override or coach_model_for(request.app.state.settings)


@router.post(
    "/{opportunity_id}/coach",
    status_code=201,
    summary="Ask the optional AI coach for advice on a deal's forecast",
    description="The coach sees only the forecast the CRM worked out (level, score, reasons) and "
    "writes up to three short pieces of advice; it may suggest up to two follow-up tasks, which "
    "wait in the approval queue for a different person. It never changes the score or the deal. "
    "Off until an administrator switches it on (503); over a limit 429; a deal you may not read, "
    "a closed deal or a made-up id 404. Nothing but the deal id is accepted.",
    responses=problem_responses(401, 403, 404, 422, 429, 503),
)
def ask_coach(
    opportunity_id: uuid.UUID,
    principal: Reader,
    session: Db,
    request: Request,
    model: Annotated[ChatModel, Depends(coach_model)],
) -> DealRiskCoachRead:
    settings: Settings = request.app.state.settings
    try:
        result = coach.run_coach(
            session,
            principal,
            model,
            opportunity_id,
            limits=coach.CoachLimits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except coach.AdviceInvalidError:
        session.commit()  # the model was called: keep the tokens it used on the month's total
        raise
    session.commit()
    return DealRiskCoachRead(
        opportunity_id=opportunity_id,
        advice=[DealRiskAdviceLine(text=a.text, factors=list(a.factors)) for a in result.advice],
        proposals=[
            DealRiskProposalRef(id=p.id, link=f"/approvals/{p.id}") for p in result.proposals
        ],
        blocked_messages=list(result.blocked),
        cleaned=result.cleaned,
    )
