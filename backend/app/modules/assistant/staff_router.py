"""Staff AI assistant endpoint (/api/v1/assistant). Support-first, read-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.assistant import staff_service
from app.modules.assistant.llm import ChatModel
from app.modules.assistant.staff_schemas import StaffAnswer, StaffQuestion
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
def ask(body: StaffQuestion, principal: Staff, session: Db, model: Model) -> StaffAnswer:
    answer, ticket_id, links = staff_service.answer(
        session,
        principal,
        model,
        question=body.question,
        ticket_id=body.ticket_id or None,
    )
    return StaffAnswer(answer=answer, ticket_id=ticket_id, links=links)
