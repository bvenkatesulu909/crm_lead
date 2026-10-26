"""Staff AI assistant endpoint (/api/v1/assistant). Support-first; it reads, and it may only
propose changes for approval (ADR 0014)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.assistant import staff_service, staff_tools
from app.modules.assistant.llm import ChatModel
from app.modules.assistant.staff_schemas import ProposalRead, StaffAnswer, StaffQuestion
from app.modules.identity.api import require_any_permission

Db = Annotated[Session, Depends(get_db_session)]
Staff = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.TICKET_READ_ALL, Permission.TICKET_READ_OWN_ACCOUNTS)
    ),
]


def chat_model(request: Request) -> ChatModel:
    model: ChatModel = request.app.state.chat_model
    return model


Model = Annotated[ChatModel, Depends(chat_model)]

router = APIRouter(
    prefix="/assistant",
    tags=["assistant"],
    responses=problem_responses(401, 403, 404, 422),
)


@router.post("/ask", summary="Ask the staff assistant about a ticket")
def ask(
    body: StaffQuestion, principal: Staff, session: Db, model: Model, request: Request
) -> StaffAnswer:
    settings: Settings = request.app.state.settings
    answer, ticket_id, links, proposals = staff_service.answer(
        session,
        principal,
        model,
        question=body.question,
        ticket_id=body.ticket_id or None,
        budget=staff_tools.ProposalBudget(
            expiry_days=settings.agent_action_expiry_days,
            pending_limit=settings.agent_action_pending_per_user,
        ),
        limits=agents_api.Limits.from_settings(settings),
    )
    # Proposals the assistant made are stored now (they wait for approval); nothing else changed.
    session.commit()
    return StaffAnswer(
        answer=answer,
        ticket_id=ticket_id,
        links=links,
        proposals=[
            ProposalRead(id=p.id, description=p.description, status=p.status, link=p.link)
            for p in proposals
        ],
    )
