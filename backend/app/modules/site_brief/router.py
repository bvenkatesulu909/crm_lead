"""/api/v1/leads/{lead_id}/brief - the rep's brief before a site visit (ADR 0029, staff only).

Thin layer: the coarse permission, then the service (which checks the person may read the lead -
else 404). Read-only: it commits nothing and writes nothing."""

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.site_brief import rules, service
from app.modules.site_brief.schemas import BriefBuyer, BriefRead

router = APIRouter(prefix="/leads", tags=["site-brief"], responses=problem_responses(401, 403))
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.BUYER_MEMORY_READ))]


@router.get(
    "/{lead_id}/brief",
    summary="The rep's brief before a site visit (built on demand, nothing is stored)",
    responses=problem_responses(404, 422),
)
def read_brief(
    lead_id: uuid.UUID,
    principal: Reader,
    session: Db,
    place: Annotated[
        str | None,
        Query(
            max_length=400,
            description="Where the visit is, for this one view (cleaned, at most 100 characters).",
        ),
    ] = None,
) -> BriefRead:
    brief = service.build(session, principal, lead_id, place)
    data = asdict(brief)
    buyer = data.pop("buyer")
    data["buyer"] = BriefBuyer(
        name=buyer["name"],
        status=buyer["status"],
        source=buyer["source"],
        owner=buyer["owner_name"],
        phone=buyer["phone"],
        email=buyer["email"],
        language=buyer["language"],
        language_label=rules.LANGUAGE_NAMES.get(buyer["language"] or ""),
    )
    data["assumptions"] = data.pop("guesses")
    return BriefRead.model_validate(data)
