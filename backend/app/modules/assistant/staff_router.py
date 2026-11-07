"""Staff AI assistant endpoint (/api/v1/assistant). Support-first; it reads, and it may only
propose changes for approval (ADR 0014).

- ``POST /assistant/ask``: one question, one complete answer (no memory).
- ``POST /assistant/conversations`` + ``.../{id}/turns`` (ADR 0023): a remembered conversation whose
  answers are streamed sentence by sentence as Server-Sent Events, so the first sentence can be
  shown and spoken while the rest is still being written.
"""

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import DomainError, problem_responses
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.assistant import staff_conversations, staff_service, staff_tools
from app.modules.assistant.llm import ChatModel
from app.modules.assistant.staff_schemas import (
    ProposalRead,
    StaffAnswer,
    StaffConversationRead,
    StaffQuestion,
    StaffTurnRequest,
    TurnRead,
)
from app.modules.identity.api import require_any_permission

logger = logging.getLogger(__name__)

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


def _budget(settings: Settings) -> staff_tools.ProposalBudget:
    return staff_tools.ProposalBudget(
        expiry_days=settings.agent_action_expiry_days,
        pending_limit=settings.agent_action_pending_per_user,
        sentinel=approvals_api.SentinelLimits.from_settings(settings),
        settings=settings,
    )


def _proposals(made: list[staff_tools.ProposalRef]) -> list[ProposalRead]:
    return [
        ProposalRead(id=p.id, description=p.description, status=p.status, link=p.link) for p in made
    ]


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
        budget=_budget(settings),
        limits=agents_api.Limits.from_settings(settings),
    )
    # Proposals the assistant made are stored now (they wait for approval); nothing else changed.
    session.commit()
    return StaffAnswer(
        answer=answer, ticket_id=ticket_id, links=links, proposals=_proposals(proposals)
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation with the staff assistant",
)
def start_conversation(principal: Staff, session: Db) -> StaffConversationRead:
    conversation = staff_conversations.start(session, principal)
    session.commit()
    return StaffConversationRead(id=conversation.id, turns=[])


@router.get(
    "/conversations/{conversation_id}",
    summary="Read one of your own conversations with the staff assistant",
)
def read_conversation(
    conversation_id: uuid.UUID, principal: Staff, session: Db
) -> StaffConversationRead:
    conversation = staff_conversations.own(session, principal, conversation_id)
    return StaffConversationRead(
        id=conversation.id,
        turns=[
            TurnRead(role=t.role, content=t.content, created_at=t.created_at)
            for t in staff_conversations.turns(session, conversation)
        ],
    )


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/conversations/{conversation_id}/turns",
    summary="Ask the next question; the answer streams as Server-Sent Events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "text/event-stream. Events: `sentence` {text} (one cleaned sentence), `working` "
                "{} (tools are running), then `done` {answer, ticket_id, links, proposals} or "
                "`error` {code, detail}. Nothing is stored when it ends with `error`."
            ),
            "content": {"text/event-stream": {}},
        },
        **problem_responses(409, 503),
    },
)
def ask_in_conversation(
    conversation_id: uuid.UUID,
    body: StaffTurnRequest,
    principal: Staff,
    session: Db,
    model: Model,
    request: Request,
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    conversation = staff_conversations.own(session, principal, conversation_id)
    staff_conversations.check_room(conversation)
    # Every refusal that can be known up front (screening, registry, ticket) is a normal error
    # response here - before the stream starts.
    prepared = staff_service.prepare(
        session,
        principal,
        model,
        question=body.question,
        ticket_id=body.ticket_id or None,
        history=staff_conversations.history(session, conversation),
        voice=body.mode == "voice",
        budget=_budget(settings),
        limits=agents_api.Limits.from_settings(settings),
        precheck=True,
    )

    def events() -> Iterator[str]:
        try:
            finished: staff_service.Finished | None = None
            for event in staff_service.run(session, principal, prepared, stream=True):
                if isinstance(event, staff_service.Sentence):
                    yield _event("sentence", {"text": event.text})
                elif isinstance(event, staff_service.Working):
                    yield _event("working", {})
                else:
                    finished = event
            if finished is None:  # pragma: no cover - run() always finishes
                raise RuntimeError("the answer did not finish")
            staff_conversations.record(
                session, conversation, question=prepared.question, answer=finished.answer
            )
            # One commit: the remembered turn and any proposal (it waits for approval).
            session.commit()
            yield _event(
                "done",
                {
                    "answer": finished.answer,
                    "ticket_id": str(finished.ticket_id),
                    "links": finished.links,
                    "proposals": [
                        p.model_dump(mode="json") for p in _proposals(finished.proposals)
                    ],
                },
            )
        except DomainError as exc:
            session.rollback()
            yield _event("error", {"code": exc.code, "detail": exc.detail})
        except Exception:  # noqa: BLE001 - the stream has started: end it with a clean error
            session.rollback()
            logger.exception("staff assistant stream failed")
            yield _event(
                "error",
                {"code": "assistant_unavailable", "detail": "The assistant could not answer."},
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-transform / X-Accel-Buffering: proxies must pass each sentence on at once.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
