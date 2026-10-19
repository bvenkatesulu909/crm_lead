"""HTTP endpoints for leads, mounted at /api/v1/leads.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
Record-level rules (which leads) live in policies.py; business rules in service.py.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.leads import service
from app.modules.leads.repository import LeadFilters
from app.modules.leads.schemas import (
    ActivityCreate,
    ActivityRead,
    AssignmentRead,
    ConversionResult,
    LeadAssign,
    LeadConvert,
    LeadCreate,
    LeadDisqualify,
    LeadPage,
    LeadPriority,
    LeadQualify,
    LeadRead,
    LeadScore,
    LeadSort,
    LeadSource,
    LeadStatus,
    LeadStatusChange,
    LeadUpdate,
)

router = APIRouter(prefix="/leads", tags=["leads"], responses=problem_responses(401, 403))

can_read = require_any_permission(Permission.LEAD_READ_ALL, Permission.LEAD_READ_OWN)
can_write = require_any_permission(Permission.LEAD_WRITE_ALL, Permission.LEAD_WRITE_OWN)
can_assign = require_any_permission(Permission.LEAD_ASSIGN)
can_convert = require_any_permission(Permission.LEAD_CONVERT)

Reader = Annotated[Principal, Depends(can_read)]
Writer = Annotated[Principal, Depends(can_write)]
Db = Annotated[Session, Depends(get_db_session)]
LeadId = Annotated[uuid.UUID, "Lead ID"]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a lead",
    description="Sales staff become the owner automatically. Choosing another owner requires "
    "`lead:assign`.",
    responses=problem_responses(422),
)
def create_lead(data: LeadCreate, principal: Writer, session: Db, response: Response) -> LeadRead:
    lead = service.create_lead(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/leads/{lead.id}"
    return LeadRead.model_validate(lead)


@router.get(
    "",
    summary="List and search leads",
    description="Only leads you may see are returned and counted. `q` searches first name, last "
    "name, company and e-mail (case-insensitive, substring).",
    responses=problem_responses(422),
)
def list_leads(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    lead_status: Annotated[list[LeadStatus] | None, Query(alias="status")] = None,
    owner_id: uuid.UUID | None = None,
    account_id: Annotated[
        uuid.UUID | None, Query(description="Only leads converted into this account")
    ] = None,
    source: LeadSource | None = None,
    priority: LeadPriority | None = Query(default=None, description="Lead score band"),
    created_from: Annotated[datetime | None, Query(description="Inclusive, ISO 8601")] = None,
    created_to: Annotated[datetime | None, Query(description="Exclusive, ISO 8601")] = None,
    sort: LeadSort = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> LeadPage:
    filters = LeadFilters(
        q=q.strip() if q else None,
        statuses=tuple(lead_status or ()),
        owner_id=owner_id,
        account_id=account_id,
        source=source,
        priority=priority,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_leads(session, principal, filters)
    return LeadPage(
        items=service.with_scores(session, principal, items),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{lead_id}", summary="Get one lead", responses=problem_responses(404))
def get_lead(lead_id: LeadId, principal: Reader, session: Db) -> LeadRead:
    lead = service.get_lead(session, principal, lead_id)
    return service.with_scores(session, principal, [lead])[0]


@router.get(
    "/{lead_id}/score",
    summary="Lead score and the factors behind it",
    responses=problem_responses(404),
)
def get_score(lead_id: LeadId, principal: Reader, session: Db) -> LeadScore:
    return service.lead_score(session, principal, lead_id)


@router.patch(
    "/{lead_id}",
    summary="Update lead details",
    description="Send the fields to change and the `version` you last read. A different "
    "version means someone else changed the lead: you get 409 `version_conflict`. Status and "
    "owner have their own endpoints.",
    responses=problem_responses(404, 409, 422),
)
def update_lead(lead_id: LeadId, data: LeadUpdate, principal: Writer, session: Db) -> LeadRead:
    lead = service.update_lead(session, principal, lead_id, data)
    session.commit()
    return LeadRead.model_validate(lead)


@router.post(
    "/{lead_id}/assign",
    summary="Assign the lead to a sales employee",
    description="Requires `lead:assign`. The new owner must be an active sales agent or sales "
    "manager of your organisation. Recorded in the assignment history and audit log.",
    responses=problem_responses(404, 409, 422),
)
def assign_lead(
    lead_id: LeadId,
    data: LeadAssign,
    principal: Annotated[Principal, Depends(can_assign)],
    session: Db,
) -> LeadRead:
    lead = service.assign_lead(session, principal, lead_id, data.owner_id, data.reason)
    session.commit()
    return LeadRead.model_validate(lead)


@router.post(
    "/{lead_id}/status",
    summary="Change the lead status",
    description="Allowed: new→contacted|qualified|unqualified, contacted→qualified|unqualified, "
    "qualified→contacted|unqualified, unqualified→contacted. Anything else: 409 "
    "`invalid_status_transition`. Converted leads cannot change.",
    responses=problem_responses(404, 409, 422),
)
def change_status(
    lead_id: LeadId, data: LeadStatusChange, principal: Writer, session: Db
) -> LeadRead:
    lead = service.change_status(session, principal, lead_id, data.status, data.reason)
    session.commit()
    return LeadRead.model_validate(lead)


@router.post(
    "/{lead_id}/qualify",
    summary="Qualify the lead",
    responses=problem_responses(404, 409, 422),
)
def qualify_lead(lead_id: LeadId, data: LeadQualify, principal: Writer, session: Db) -> LeadRead:
    lead = service.change_status(session, principal, lead_id, "qualified", data.reason)
    session.commit()
    return LeadRead.model_validate(lead)


@router.post(
    "/{lead_id}/disqualify",
    summary="Disqualify the lead (reason required)",
    responses=problem_responses(404, 409, 422),
)
def disqualify_lead(
    lead_id: LeadId, data: LeadDisqualify, principal: Writer, session: Db
) -> LeadRead:
    lead = service.change_status(session, principal, lead_id, "unqualified", data.reason)
    session.commit()
    return LeadRead.model_validate(lead)


@router.post(
    "/{lead_id}/convert",
    status_code=status.HTTP_201_CREATED,
    summary="Convert a qualified lead",
    description="Creates (or links) an account, creates a contact and optionally an "
    "opportunity, in ONE transaction: either everything is created or nothing. Only qualified "
    "leads can be converted. **Idempotent:** repeating the call for a converted lead returns "
    "the original result with `already_converted: true` and status 200, creating nothing.",
    responses={
        200: {"model": ConversionResult, "description": "Already converted earlier."},
        **problem_responses(404, 409, 422),
    },
)
def convert_lead(
    lead_id: LeadId,
    data: LeadConvert,
    principal: Annotated[Principal, Depends(can_convert)],
    session: Db,
    response: Response,
) -> ConversionResult:
    result = service.convert_lead(session, principal, lead_id, data)
    session.commit()
    if result.already_converted:
        response.status_code = status.HTTP_200_OK
    return result


@router.get(
    "/{lead_id}/activities",
    summary="Lead timeline (activities and system events)",
    responses=problem_responses(404),
)
def list_activities(lead_id: LeadId, principal: Reader, session: Db) -> list[ActivityRead]:
    return [
        ActivityRead.model_validate(a) for a in service.list_activities(session, principal, lead_id)
    ]


@router.post(
    "/{lead_id}/activities",
    status_code=status.HTTP_201_CREATED,
    summary="Record a call, e-mail, meeting or note",
    responses=problem_responses(404, 422),
)
def add_activity(
    lead_id: LeadId, data: ActivityCreate, principal: Writer, session: Db
) -> ActivityRead:
    activity = service.add_activity(session, principal, lead_id, data)
    session.commit()
    return ActivityRead.model_validate(activity)


@router.get(
    "/{lead_id}/assignments",
    summary="Assignment history (who owned the lead, who changed it, why)",
    responses=problem_responses(404),
)
def list_assignments(lead_id: LeadId, principal: Reader, session: Db) -> list[AssignmentRead]:
    return [
        AssignmentRead.model_validate(a)
        for a in service.list_assignments(session, principal, lead_id)
    ]
