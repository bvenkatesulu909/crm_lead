"""Communication Center endpoints at /api/v1/communications (staff only, ADR 0012).

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.communications import service
from app.modules.communications.schemas import (
    EmailMessageRead,
    EmailSend,
    PlaceholderRead,
    TemplateCreate,
    TemplatePreview,
    TemplatePreviewRequest,
    TemplateRead,
    TemplateUpdate,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(
    prefix="/communications", tags=["communications"], responses=problem_responses(401, 403)
)
Sender = Annotated[Principal, Depends(require_any_permission(Permission.COMMUNICATION_SEND))]
Reader = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.COMMUNICATION_READ_ALL, Permission.COMMUNICATION_READ_OWN)
    ),
]
TemplateUser = Annotated[
    Principal,
    Depends(
        require_any_permission(
            Permission.COMMUNICATION_SEND, Permission.COMMUNICATION_TEMPLATE_MANAGE
        )
    ),
]
TemplateManager = Annotated[
    Principal, Depends(require_any_permission(Permission.COMMUNICATION_TEMPLATE_MANAGE))
]
Db = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/emails",
    status_code=status.HTTP_201_CREATED,
    summary="Write an e-mail to a lead or contact; the worker sends it",
    responses=problem_responses(404, 409, 422, 429),
)
def send_email(
    data: EmailSend, principal: Sender, session: Db, request: Request, response: Response
) -> EmailMessageRead:
    limit: int = request.app.state.settings.communication_emails_per_hour
    message = service.send_email(session, principal, data, hourly_limit=limit)
    session.commit()
    response.headers["Location"] = f"/api/v1/communications/emails/{message.id}"
    return EmailMessageRead.model_validate(message)


@router.get(
    "/emails/{message_id}",
    summary="One e-mail you sent (or, for managers, any e-mail) and its status",
    responses=problem_responses(404),
)
def get_email(message_id: uuid.UUID, principal: Reader, session: Db) -> EmailMessageRead:
    return EmailMessageRead.model_validate(service.get_message(session, principal, message_id))


# --- templates (step CC3) -----------------------------------------------------------------


@router.get("/placeholders", summary="The placeholders templates may use")
def list_placeholders(principal: TemplateUser) -> list[PlaceholderRead]:
    return service.placeholders()


@router.get("/templates", summary="E-mail templates (active ones; managers may add inactive)")
def list_templates(
    principal: TemplateUser,
    session: Db,
    include_inactive: Annotated[
        bool, Query(description="Managers only; ignored for everyone else.")
    ] = False,
) -> list[TemplateRead]:
    templates = service.list_templates(session, principal, include_inactive=include_inactive)
    return [TemplateRead.model_validate(t) for t in templates]


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    summary="Create a template (managers and tenant admins)",
    responses=problem_responses(409, 422),
)
def create_template(
    data: TemplateCreate, principal: TemplateManager, session: Db, response: Response
) -> TemplateRead:
    template = service.create_template(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/communications/templates/{template.id}"
    return TemplateRead.model_validate(template)


@router.get("/templates/{template_id}", summary="One template", responses=problem_responses(404))
def get_template(template_id: uuid.UUID, principal: TemplateUser, session: Db) -> TemplateRead:
    return TemplateRead.model_validate(service.get_template(session, principal, template_id))


@router.patch(
    "/templates/{template_id}",
    summary="Change, deactivate or reactivate a template (managers and tenant admins)",
    responses=problem_responses(404, 409, 422),
)
def update_template(
    template_id: uuid.UUID, data: TemplateUpdate, principal: TemplateManager, session: Db
) -> TemplateRead:
    template = service.update_template(session, principal, template_id, data)
    session.commit()
    return TemplateRead.model_validate(template)


@router.post(
    "/templates/{template_id}/preview",
    summary="The template filled in for a lead or contact you may see (or sample values)",
    responses=problem_responses(404, 422),
)
def preview_template(
    template_id: uuid.UUID, data: TemplatePreviewRequest, principal: TemplateUser, session: Db
) -> TemplatePreview:
    return service.preview_template(session, principal, template_id, data)
