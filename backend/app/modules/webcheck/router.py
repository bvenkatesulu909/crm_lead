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
from app.modules.webcheck import company_details, service
from app.modules.webcheck.schemas import (
    CompanyCurrent,
    CompanyDetailsApply,
    CompanyDetailsAsk,
    CompanyDetailsRead,
    CompanySuggestionRead,
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


# --- company details on a lead (BP-02, ADR 0026) -------------------------------------------------


def _details(found: company_details.CompanyDetails) -> CompanyDetailsRead:
    current = found.current
    row = found.latest
    latest = None
    if row is not None:
        suggestions = row.suggestions if isinstance(row.suggestions, dict) else {}

        def text(key: str) -> str | None:
            value = suggestions.get(key)
            return value if isinstance(value, str) else None

        pages = suggestions.get("pages")
        latest = CompanySuggestionRead(
            id=row.id,
            created_at=row.created_at,
            verdict=row.verdict,
            error_code=row.error_code,
            company_website=text("website"),
            company_industry=text("industry"),
            company_size=text("size"),
            name=row.registered_name,
            excerpt=row.excerpt,
            pages=[p for p in pages if isinstance(p, str)] if isinstance(pages, list) else [],
            cleaned=list(row.cleaned),
        )
    return CompanyDetailsRead(
        current=CompanyCurrent(
            company_website=current.website,
            company_industry=current.industry,
            company_size=current.size,
            version=current.version,
        ),
        latest=latest,
    )


@router.post(
    "/company-details",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Look up the company of a lead on its own website (read in the background)",
    responses=problem_responses(404, 422, 429, 503),
)
def ask_company_details(
    body: CompanyDetailsAsk, request: Request, principal: Runner, session: Db
) -> WebCheckAccepted:
    asked = company_details.request_lookup(
        session, principal, body.lead_id, settings=request.app.state.settings
    )
    session.commit()
    return WebCheckAccepted(request_id=asked.request_id)


@router.get(
    "/company-details",
    summary="A lead's company fields next to the newest suggestions from its website",
    responses=problem_responses(404),
)
def read_company_details(principal: Reader, session: Db, lead_id: uuid.UUID) -> CompanyDetailsRead:
    return _details(company_details.company_details(session, principal, lead_id))


@router.post(
    "/company-details/apply",
    summary="Save chosen suggestions on the lead (values come from the stored evidence)",
    responses=problem_responses(404, 409, 422),
)
def apply_company_details(
    body: CompanyDetailsApply, principal: Runner, session: Db
) -> CompanyDetailsRead:
    company_details.apply_suggestions(
        session,
        principal,
        body.lead_id,
        evidence_id=body.evidence_id,
        fields=list(body.fields),
        version=body.version,
    )
    session.commit()
    return _details(company_details.company_details(session, principal, body.lead_id))
