"""Communication Center endpoints at /api/v1/communications (staff only, ADR 0012).

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.communications import service
from app.modules.communications.schemas import EmailMessageRead, EmailSend
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
