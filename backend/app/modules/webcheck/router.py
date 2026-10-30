"""/api/v1/webcheck - ask for a web check and read its evidence (ADR 0019, staff only).

Thin layer: the coarse permission, then the service (which also checks that the person may read
the lead or account, the source, the query and the limits); the write endpoint commits once.
Asking is quick and answers 202: the page is fetched by the worker, later.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.webcheck import service
from app.modules.webcheck.schemas import (
    WebCheckAccepted,
    WebCheckRequest,
    WebCheckSourcePage,
    WebCheckSourceRead,
    WebEvidencePage,
    WebEvidenceRead,
)

router = APIRouter(prefix="/webcheck", tags=["webcheck"], responses=problem_responses(401, 403))
Db = Annotated[Session, Depends(get_db_session)]
Runner = Annotated[Principal, Depends(require_any_permission(Permission.WEBCHECK_RUN))]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.WEBCHECK_READ))]


@router.get("/sources", summary="The sources a check can look at (those switched on)")
def list_sources(request: Request, principal: Runner) -> WebCheckSourcePage:
    sources = service.offered_sources(request.app.state.settings)
    return WebCheckSourcePage(
        items=[
            WebCheckSourceRead(
                key=s.key, title=s.title, kind=s.kind, query_hint=s.query_hint, demo=s.demo
            )
            for s in sources
        ]
    )


@router.post(
    "/checks",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a web check of a lead or an account (fetched in the background)",
    responses=problem_responses(404, 422, 429, 503),
)
def request_check(
    body: WebCheckRequest, request: Request, principal: Runner, session: Db
) -> WebCheckAccepted:
    asked = service.request_check(
        session,
        principal,
        target_type=body.target_type,
        target_id=body.target_id,
        source_key=body.source_key,
        query=body.query,
        settings=request.app.state.settings,
    )
    session.commit()
    return WebCheckAccepted(request_id=asked.request_id)


@router.get(
    "/evidence",
    summary="The evidence of web checks about one lead or account, newest first",
    responses=problem_responses(404, 422),
)
def list_evidence(
    principal: Reader,
    session: Db,
    target_type: Annotated[str, Query(min_length=1, max_length=20)],
    target_id: uuid.UUID,
) -> WebEvidencePage:
    rows = service.list_evidence(session, principal, target_type, target_id)
    return WebEvidencePage(items=[WebEvidenceRead.model_validate(row) for row in rows])
