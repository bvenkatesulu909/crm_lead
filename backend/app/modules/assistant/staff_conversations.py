"""The staff assistant's conversation memory (ADR 0023, step VM1).

Why it exists: without it every question starts from zero, so a spoken follow-up ("and the second
one?") cannot be understood. Why it is on the SERVER: if the browser sent the history, a person
could forge an "assistant said ..." turn. Here the history is only what the server itself stored:
the question after input screening and the answer after exit cleaning.

Rules: a conversation belongs to one employee (tenant and user from the verified token); any other
person - a colleague, another organisation - gets 404, the same as an id that does not exist. Only
the last ``MEMORY_TURNS`` turns go back to the model. Quiet conversations are deleted by the worker.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.modules.assistant.staff_models import MAX_TURN_CHARS, StaffConversation, StaffTurn

MEMORY_TURNS = 6  # what the model sees again: the last three questions and answers
MAX_TURNS = 200  # one conversation; then the person starts a new one


class StaffConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"

    def __init__(self) -> None:
        super().__init__("Conversation not found.")


class ConversationFullError(ConflictError):
    code = "conversation_full"

    def __init__(self) -> None:
        super().__init__("This conversation is very long. Please start a new one.")


@dataclass(frozen=True)
class TurnView:
    role: str
    content: str
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _person(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.user_type != "staff" or principal.tenant_id is None or principal.user_id is None:
        raise ForbiddenError("The staff assistant is only for employees.")
    return principal.tenant_id, principal.user_id


def start(session: Session, principal: Principal, now: datetime | None = None) -> StaffConversation:
    """A new, empty conversation of the signed-in employee (not committed)."""
    tenant_id, user_id = _person(principal)
    conversation = StaffConversation(
        tenant_id=tenant_id, user_id=user_id, last_turn_at=now or _now(), turn_count=0
    )
    session.add(conversation)
    session.flush()
    return conversation


def own(session: Session, principal: Principal, conversation_id: uuid.UUID) -> StaffConversation:
    """The employee's own conversation, or 404 (also for a colleague's or another tenant's)."""
    tenant_id, user_id = _person(principal)
    conversation = session.scalar(
        select(StaffConversation).where(
            StaffConversation.tenant_id == tenant_id,
            StaffConversation.user_id == user_id,
            StaffConversation.id == conversation_id,
        )
    )
    if conversation is None:
        raise StaffConversationNotFoundError()
    return conversation


def check_room(conversation: StaffConversation) -> None:
    if conversation.turn_count + 2 > MAX_TURNS:
        raise ConversationFullError()


def history(session: Session, conversation: StaffConversation) -> list[dict[str, Any]]:
    """The last turns as model messages, oldest first (plain text only, no tool blocks)."""
    rows = list(
        session.scalars(
            select(StaffTurn)
            .where(
                StaffTurn.tenant_id == conversation.tenant_id,
                StaffTurn.conversation_id == conversation.id,
            )
            .order_by(StaffTurn.seq.desc())
            .limit(MEMORY_TURNS)
        )
    )
    rows.reverse()
    # The model's history must start with a question: drop an answer whose question fell off.
    while rows and rows[0].role != "user":
        rows.pop(0)
    return [{"role": row.role, "content": row.content} for row in rows]


def turns(session: Session, conversation: StaffConversation) -> list[TurnView]:
    rows = session.scalars(
        select(StaffTurn)
        .where(
            StaffTurn.tenant_id == conversation.tenant_id,
            StaffTurn.conversation_id == conversation.id,
        )
        .order_by(StaffTurn.seq)
    )
    return [TurnView(row.role, row.content, row.created_at) for row in rows]


def record(
    session: Session,
    conversation: StaffConversation,
    *,
    question: str,
    answer: str,
    now: datetime | None = None,
) -> None:
    """Store one finished turn (not committed). Only screened / cleaned text comes here."""
    check_room(conversation)
    for role, content in (("user", question), ("assistant", answer)):
        session.add(
            StaffTurn(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                role=role,
                content=content[:MAX_TURN_CHARS],
            )
        )
    conversation.turn_count += 2
    conversation.last_turn_at = now or _now()
    session.flush()


def delete_stale(
    session: Session, now: datetime, *, tenant_id: uuid.UUID, retention_hours: int
) -> int:
    """Delete the tenant's conversations quiet for ``retention_hours`` (their turns go too)."""
    result = session.execute(
        delete(StaffConversation).where(
            StaffConversation.tenant_id == tenant_id,
            StaffConversation.last_turn_at < now - timedelta(hours=retention_hours),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
