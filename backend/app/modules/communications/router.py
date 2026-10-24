"""Communication Center endpoints at /api/v1/communications (staff only, ADR 0012).

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.communications import service
from app.modules.communications.models import EmailMessage
from app.modules.communications.repository import MessageFilters
from app.modules.communications.schemas import (
    Direction,
    EmailLogReceived,
    EmailMessageRead,
    EmailPage,
    EmailSend,
    MessageStatus,
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
HistoryReader = Annotated[
    Principal,
    Depends(
        require_any_permission(
            Permission.COMMUNICATION_SEND,
            Permission.COMMUNICATION_READ_ALL,
            Permission.COMMUNICATION_READ_OWN,
        )
    ),
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


# --- history, list and logged e-mails (step CC4) ------------------------------------------


@router.get("/emails", summary="The Communication Center: e-mails you may see, newest first")
def list_emails(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    message_status: Annotated[MessageStatus | None, Query(alias="status")] = None,
    direction: Direction | None = None,
    sent_by_user_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> EmailPage:
    filters = MessageFilters(
        q=q,
        status=message_status,
        direction=direction,
        sent_by_user_id=sent_by_user_id,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_messages(session, principal, filters)
    return _page(items, total, limit, offset)


@router.post(
    "/emails/received",
    status_code=status.HTTP_201_CREATED,
    summary="Log an e-mail a lead or contact sent you (nothing is sent)",
    responses=problem_responses(404, 409, 422),
)
def log_received_email(
    data: EmailLogReceived, principal: Sender, session: Db, response: Response
) -> EmailMessageRead:
    message = service.log_received(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/communications/emails/{message.id}"
    return EmailMessageRead.model_validate(message)


@router.get(
    "/history",
    summary="Every e-mail of one lead, contact, account or deal you may see (newest first)",
    responses=problem_responses(404, 422),
)
def record_history(
    principal: HistoryReader,
    session: Db,
    lead_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> EmailPage:
    items, total = service.record_history(
        session,
        principal,
        lead_id=lead_id,
        contact_id=contact_id,
        account_id=account_id,
        opportunity_id=opportunity_id,
        limit=limit,
        offset=offset,
    )
    return _page(items, total, limit, offset)


def _page(items: Sequence[EmailMessage], total: int, limit: int, offset: int) -> EmailPage:
    return EmailPage(
        items=[EmailMessageRead.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )
