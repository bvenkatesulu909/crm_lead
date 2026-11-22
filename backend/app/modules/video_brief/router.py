"""/api/v1/leads/{lead_id}/video-brief - the brief for a personalised buyer video (ADR 0041, staff).

Thin layer: the coarse permission, then the service (which checks the person may read the lead -
else 404). Read-only: it commits nothing and writes nothing."""

import uuid
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.video_brief import service
from app.modules.video_brief.models import VideoScript
from app.modules.video_brief.schemas import ScriptCreate, ScriptPage, ScriptRead, VideoBriefRead

router = APIRouter(prefix="/leads", tags=["video-brief"], responses=problem_responses(401, 403))
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.VIDEO_BRIEF_READ))]
Writer = Annotated[Principal, Depends(require_any_permission(Permission.VIDEO_BRIEF_WRITE))]


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
    quote_id: Annotated[
        uuid.UUID | None,
        Query(description="An approved, sent or accepted quote of the account this lead became."),
    ] = None,
) -> VideoBriefRead:
    brief = service.build(
        session,
        principal,
        lead_id,
        goal=goal,
        language=language,
        tone=tone,
        length_seconds=length,
        quote_id=quote_id,
    )
    return VideoBriefRead.model_validate(asdict(brief))


def _script_read(row: VideoScript) -> ScriptRead:
    return ScriptRead(
        id=row.id,
        version=row.version,
        source=row.source,
        language=row.language,
        tone=row.tone,
        goal=row.goal,
        length_seconds=row.length_seconds,
        lines=list(row.lines),
        words=row.words,
        created_by=row.created_by_user_id,
        created_at=row.created_at,
    )


@router.post(
    "/{lead_id}/video-scripts",
    status_code=status.HTTP_201_CREATED,
    summary="Save a hand-written script for this buyer's video (a new version)",
    responses=problem_responses(404, 422, 429),
)
def save_video_script(
    lead_id: uuid.UUID,
    data: ScriptCreate,
    principal: Writer,
    session: Db,
    request: Request,
) -> ScriptRead:
    settings: Settings = request.app.state.settings
    row = service.save_script(
        session,
        principal,
        lead_id,
        language=data.language,
        tone=data.tone,
        goal=data.goal,
        length_seconds=data.length_seconds,
        lines=data.lines,
        per_user_hour=settings.video_scripts_per_user_hour,
    )
    result = _script_read(row)
    session.commit()
    return result


@router.get(
    "/{lead_id}/video-scripts",
    summary="The saved scripts of this buyer's video, newest first",
    responses=problem_responses(404),
)
def list_video_scripts(lead_id: uuid.UUID, principal: Reader, session: Db) -> ScriptPage:
    return ScriptPage(
        items=[_script_read(row) for row in service.list_scripts(session, principal, lead_id)]
    )
