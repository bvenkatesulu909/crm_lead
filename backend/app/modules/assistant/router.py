"""Customer-portal assistant endpoints (/api/v1/portal/assistant). Thin: permission gate,
call the service, commit once."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.assistant import service
from app.modules.assistant.llm import ChatModel
from app.modules.assistant.schemas import (
    AssistantStatus,
    ConversationRead,
    ConversationSummary,
    MessageCreate,
)
from app.modules.identity.api import require_any_permission

Db = Annotated[Session, Depends(get_db_session)]
Customer = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_ASSISTANT_USE))]


def chat_model(request: Request) -> ChatModel:
    model: ChatModel = request.app.state.chat_model
    return model


Model = Annotated[ChatModel, Depends(chat_model)]

router = APIRouter(
    prefix="/portal/assistant", tags=["assistant"], responses=problem_responses(401, 403)
)


@router.get("/status", summary="Is the assistant available?")
def status(_: Customer, model: Model) -> AssistantStatus:
    return AssistantStatus(available=model.available)


@router.get("/conversations", summary="My recent conversations")
def conversations(principal: Customer, session: Db) -> list[ConversationSummary]:
    return service.list_conversations(session, principal)


@router.get(
    "/conversations/{conversation_id}",
    summary="One of my conversations with its prepared actions",
    responses=problem_responses(404),
)
def conversation(conversation_id: uuid.UUID, principal: Customer, session: Db) -> ConversationRead:
    return service.get_conversation(session, principal, conversation_id)


@router.post(
    "/messages",
    summary="Send a message; returns the conversation with the assistant's answer",
    description="Starts a new conversation when conversation_id is omitted. The assistant can "
    "only read your own data; handing over to support needs your confirmation.",
    responses=problem_responses(404, 409, 422, 429, 503),
)
def send(
    data: MessageCreate, principal: Customer, session: Db, model: Model, request: Request
) -> ConversationRead:
    settings = request.app.state.settings
    result = service.send_message(
        session,
        principal,
        model,
        conversation_id=data.conversation_id,
        text=data.text,
        messages_per_hour=settings.assistant_messages_per_hour,
        max_tool_rounds=settings.assistant_max_tool_rounds,
    )
    session.commit()
    return result


@router.post(
    "/actions/{action_id}/confirm",
    summary="Confirm the support ticket the assistant prepared",
    responses=problem_responses(404, 409),
)
def confirm(action_id: uuid.UUID, principal: Customer, session: Db) -> ConversationRead:
    result = service.confirm_action(session, principal, action_id)
    session.commit()
    return result


@router.post(
    "/actions/{action_id}/cancel",
    summary="Don't create the prepared ticket",
    responses=problem_responses(404, 409),
)
def cancel(action_id: uuid.UUID, principal: Customer, session: Db) -> ConversationRead:
    result = service.cancel_action(session, principal, action_id)
    session.commit()
    return result
