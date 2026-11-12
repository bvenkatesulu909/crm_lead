# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Buyer memory seeded by the website chat (ADR 0028, BM6): what the visitor gave becomes facts."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.assistant.llm import ModelReply, ToolUse
from app.modules.buyer_memory.models import BuyerMemoryItem
from app.modules.public_chat.models import PublicChatSession
from tests.db.test_public_chat_api import (  # noqa: F401 - fixtures used by name
    PHONE_MESSAGE,
    alpha,
    chat,
    leads_in,
    make_api,
)
from tests.db.test_quotes_api import world  # noqa: F401


class Scripted:
    available = True

    def __init__(self, *replies: ModelReply) -> None:
        self.replies = list(replies)

    def reply(self, *, system: str, messages: list[dict[str, Any]], tools: list[Any]) -> ModelReply:
        return self.replies.pop(0)


def items(db_session: Session, world: Any) -> list[BuyerMemoryItem]:
    bind_tenant(db_session, alpha(world))
    return list(db_session.scalars(select(BuyerMemoryItem).order_by(BuyerMemoryItem.seq)))


def test_what_the_visitor_gave_becomes_facts_with_the_conversation_as_source(
    make_api, world, db_session
) -> None:
    api = make_api()
    first = chat(api, "Hello").json()
    assert chat(api, PHONE_MESSAGE, token=first["token"]).json()["lead_saved"] is True
    [lead] = leads_in(db_session, alpha(world))
    rows = items(db_session, world)
    assert {r.key: (r.value, r.status, r.source) for r in rows} == {
        "budget": ("1.2 Cr - 1.5 Cr", "fact", "website_chat"),
        "property_type": ("Apartment", "fact", "website_chat"),
        "location": ("Kokapet, Hyderabad", "fact", "website_chat"),
    }
    bind_tenant(db_session, alpha(world))
    [conversation] = db_session.scalars(select(PublicChatSession)).all()
    assert all(r.source_ref == conversation.id and r.lead_id == lead.id for r in rows)
    assert all(r.quote and r.reason is None for r in rows)
    # Written by the organisation's Automation identity, not by a person.
    assert len({r.recorded_by_user_id for r in rows}) == 1


def test_nothing_is_guessed_when_the_visitor_gave_only_a_name_and_a_number(
    make_api, world, db_session
) -> None:
    model = Scripted(
        ModelReply(
            "", [ToolUse("t1", "save_lead", {"full_name": "Asha Rao", "phone": "98480 12345"})]
        ),
        ModelReply("Thank you."),
    )
    assert chat(make_api(model=model), "Details").json()["lead_saved"] is True
    assert items(db_session, world) == []


def test_the_notes_the_chat_wrote_are_not_turned_into_facts(make_api, world, db_session) -> None:
    model = Scripted(
        ModelReply(
            "",
            [
                ToolUse(
                    "t1",
                    "save_lead",
                    {
                        "full_name": "Asha Rao",
                        "phone": "98480 12345",
                        "notes": "Wants a big balcony",
                    },
                )
            ],
        ),
        ModelReply("Thank you."),
    )
    chat(make_api(model=model), "Details")
    assert items(db_session, world) == []


def test_a_conversation_that_saves_nothing_writes_nothing(make_api, world, db_session) -> None:
    chat(make_api(), "Hello")
    assert items(db_session, world) == []
