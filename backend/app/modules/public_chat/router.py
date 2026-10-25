"""POST /api/v1/public/chat - the public website chat (ADR 0013).

No user login: only our Next.js server may call it, proven by the X-Public-Chat-Key header
(a long shared secret). Without it - or with the feature switched off - the answer is 404, as
if the endpoint didn't exist. The visitor's address arrives in X-Visitor-Ip from that server
and is trusted only together with the key. Thin layer: check the key, call the service,
commit once.
"""

import hmac
import ipaddress
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.public_chat import service
from app.modules.public_chat.schemas import (
    PublicChatReply,
    PublicChatRequest,
    PublicChatTranscript,
)

router = APIRouter(prefix="/public", tags=["public chat"])
# Staff side: signed-in users read a lead's website conversation (never visitors).
staff_router = APIRouter(prefix="/public-chat", tags=["public chat"])
Db = Annotated[Session, Depends(get_db_session)]
LeadReader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.LEAD_READ_ALL, Permission.LEAD_READ_OWN)),
]


def require_web_server(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    key = settings.public_chat_server_key
    sent = request.headers.get("X-Public-Chat-Key", "")
    # compare_digest: the time taken doesn't reveal how much of the key was right.
    if (
        not settings.public_chat_enabled
        or key is None
        or not hmac.compare_digest(sent.encode(), key.get_secret_value().encode())
    ):
        raise service.PublicChatNotFoundError()
    return settings


def visitor_ip(request: Request) -> str:
    raw = request.headers.get("X-Visitor-Ip", "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "unknown"  # still limited, together with everyone else without an address


@router.post(
    "/chat",
    summary="A visitor's message to the website chat (only for the CRM's web server)",
    responses=problem_responses(404, 422, 429, 503),
)
def public_chat(
    data: PublicChatRequest,
    request: Request,
    session: Db,
    settings: Annotated[Settings, Depends(require_web_server)],
) -> PublicChatReply:
    reply = service.handle_message(
        session,
        settings,
        request.app.state.public_chat_model,
        data,
        visitor_ip=visitor_ip(request),
    )
    session.commit()
    return reply


@staff_router.get(
    "/leads/{lead_id}/transcript",
    summary="The website chat that created a lead you may see (empty if there was none)",
    responses=problem_responses(404),
)
def lead_transcript(lead_id: uuid.UUID, principal: LeadReader, session: Db) -> PublicChatTranscript:
    return service.lead_transcript(session, principal, lead_id)
