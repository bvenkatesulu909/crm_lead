"""/api/v1/leads/{lead_id}/video-brief - the brief for a personalised buyer video (ADR 0041, staff).

Thin layer: the coarse permission, then the service (which checks the person may read the lead -
else 404). Read-only: it commits nothing and writes nothing."""

import uuid
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.video_brief import service
from app.modules.video_brief.schemas import VideoBriefRead

router = APIRouter(prefix="/leads", tags=["video-brief"], responses=problem_responses(401, 403))
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.VIDEO_BRIEF_READ))]


@router.get(
    "/{lead_id}/video-brief",
    summary="The brief for a personalised video to this buyer (built on demand, nothing stored)",
    responses=problem_responses(404, 422),
)
def read_video_brief(
    lead_id: uuid.UUID,
    principal: Reader,
    session: Db,
    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"] = "follow_up",
    language: Annotated[
        Literal["en", "hi", "te"] | None,
        Query(description="Default: the buyer's preferred language, else English."),
    ] = None,
    tone: Literal["warm", "professional", "brisk"] = "warm",
    length: Annotated[int, Query(description="Seconds: 30, 60 or 90.")] = 60,
) -> VideoBriefRead:
    brief = service.build(
        session,
        principal,
        lead_id,
        goal=goal,
        language=language,
        tone=tone,
        length_seconds=length,
    )
    return VideoBriefRead.model_validate(asdict(brief))
