"""/api/v1/deal-desk - ask the deal desk to review one deal, and read its reviews (ADR 0024, DD3).

Thin layer: permission, then the service; it commits once. The deal desk only suggests: a task
waits in the approval queue for a different person.
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
from app.modules.deal_desk import service
from app.modules.deal_desk.llm import model_for
from app.modules.deal_desk.models import DealReview
from app.modules.deal_desk.schemas import (
    ReviewCreate,
    ReviewCreated,
    ReviewList,
    ReviewRead,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/deal-desk", tags=["deal-desk"])
Db = Annotated[Session, Depends(get_db_session)]
Runner = Annotated[Principal, Depends(require_any_permission(Permission.DEAL_DESK_RUN))]
Reader = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.OPPORTUNITY_READ_ALL, Permission.OPPORTUNITY_READ_OWN)
    ),
]


def deal_desk_model(request: Request) -> ChatModel:
    """The model behind the deal desk. Tests put a scripted one on the app."""
    override: ChatModel | None = getattr(request.app.state, "deal_desk_model", None)
    return override or model_for(request.app.state.settings)


Model = Annotated[ChatModel, Depends(deal_desk_model)]


def _read(review: DealReview) -> ReviewRead:
    return ReviewRead.model_validate(
        {
            "id": review.id,
            "opportunity_id": review.opportunity_id,
            "created_at": review.created_at,
            "brief": review.brief,
            "findings": [
                {
                    "reviewer": f["reviewer"],
                    "severity": f["severity"],
                    "text": f["text"],
                    "records": f.get("records", []),
                }
                for f in review.findings
            ],
            "reviewers": review.reviewers,
            "proposals": [{"id": p, "link": f"/approvals/{p}"} for p in review.proposal_ids],
        }
    )


@router.post(
    "/reviews",
    status_code=201,
    summary="Ask the deal desk to review one deal; it suggests, a different person decides",
    description="Three AI reviewers (pricing, account, momentum) look at the deal at the same "
    "time; a desk lead writes a short brief and may suggest at most two follow-up tasks, which "
    "wait in the approval queue. Needs a deal you may read (a sales agent: one they own) and the "
    "deal desk switched on by an administrator. Off, over budget or over a limit: 503 / 429.",
    responses=problem_responses(401, 403, 404, 422, 429, 503),
)
def create_review(
    data: ReviewCreate, principal: Runner, session: Db, request: Request, model: Model
) -> ReviewCreated:
    settings: Settings = request.app.state.settings
    try:
        result = service.run_review(
            session,
            principal,
            model,
            data.opportunity_id,
            limits=service.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except (service.NoReviewerAnsweredError, service.BriefInvalidError):
        session.commit()  # the model was called: keep the tokens it used on the month's total
        raise
    session.commit()
    read = _read(result.review)
    return ReviewCreated(**read.model_dump(), blocked_messages=result.blocked)


@router.get(
    "/reviews",
    summary="The deal desk's reviews of one deal, newest first",
    description="Only for a deal you may read; any other id answers 404.",
    responses=problem_responses(401, 403, 404),
)
def list_reviews(
    principal: Reader, session: Db, opportunity_id: Annotated[uuid.UUID, Query()]
) -> ReviewList:
    rows = service.list_reviews(session, principal, opportunity_id)
    return ReviewList(items=[_read(row) for row in rows])
