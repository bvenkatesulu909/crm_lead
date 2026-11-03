# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The anonymous daily counter of the website chat (docs/pilot-report.md, step PR1).

Two numbers per organisation and day - conversations started and leads saved - so the share of
chats that end with a lead stays true after the conversations themselves are deleted (privacy: 30
quiet days). The table holds no address, token, text or lead id; counters can only grow; tenants
never see each other's numbers.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.public_chat import repository, service
from app.modules.public_chat.models import PublicChatDailyStat, PublicChatSession
from tests.db.test_public_chat_api import (  # noqa: F401 - fixtures used by name
    PHONE_MESSAGE,
    alpha,
    chat,
    make_api,
)
from tests.db.test_quotes_api import World, world  # noqa: F401

TODAY = datetime.now(UTC).date()


def stats(db_session: Session, tenant_id: uuid.UUID) -> dict[date, tuple[int, int]]:
    bind_tenant(db_session, tenant_id)
    rows = db_session.scalars(select(PublicChatDailyStat))
    return {r.day: (r.conversations_started, r.leads_saved) for r in rows}


def beta(world: World) -> uuid.UUID:
    return world.users["beta.admin"].tenant_id


# --- what is counted ----------------------------------------------------------------------------


def test_a_new_conversation_counts_once_however_many_messages_it_has(
    make_api, db_session, world
) -> None:
    api = make_api()
    first = chat(api, "Hello").json()
    chat(api, "I am looking for a flat", token=first["token"])
    chat(api, "In Kokapet", token=first["token"])
    assert stats(db_session, alpha(world)) == {TODAY: (1, 0)}


def test_each_new_conversation_counts(make_api, db_session, world) -> None:
    api = make_api()
    chat(api, "Hello", ip="203.0.113.1")
    chat(api, "Hello", ip="203.0.113.2")
    chat(api, "Hello", ip="203.0.113.3")
    assert stats(db_session, alpha(world)) == {TODAY: (3, 0)}


def test_a_saved_lead_counts_once_even_if_the_visitor_keeps_talking(
    make_api, db_session, world
) -> None:
    api = make_api()
    first = chat(api, "Hello").json()
    saved = chat(api, PHONE_MESSAGE, token=first["token"]).json()
    assert saved["lead_saved"] is True
    chat(api, PHONE_MESSAGE, token=first["token"])  # tries again: "already passed on"
    chat(api, "Thanks!", token=first["token"])
    assert stats(db_session, alpha(world)) == {TODAY: (1, 1)}


def test_a_message_that_is_refused_before_any_conversation_counts_for_nothing(
    make_api, db_session, world
) -> None:
    api = make_api()
    refused = chat(api, "my card is 4111 1111 1111 1111")
    assert refused.status_code in (200, 400, 422)
    assert stats(db_session, alpha(world)) == {}, "no conversation was stored, so none is counted"


def test_a_message_to_a_conversation_that_does_not_exist_counts_for_nothing(
    make_api, db_session, world
) -> None:
    api = make_api()
    chat(api, "Hello", token="not-a-real-token")  # noqa: S106 - a made-up visitor token
    assert stats(db_session, alpha(world)) == {}


def test_the_day_is_the_utc_day_of_the_moment_it_happened(
    make_api, db_session, world, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = make_api()
    late = datetime(2026, 11, 20, 23, 59, 30, tzinfo=UTC)
    monkeypatch.setattr(service, "_now", lambda: late)
    chat(api, "Hello", ip="203.0.113.1")
    monkeypatch.setattr(service, "_now", lambda: late + timedelta(seconds=60))
    chat(api, "Hello", ip="203.0.113.2")
    assert stats(db_session, alpha(world)) == {
        date(2026, 11, 20): (1, 0),
        date(2026, 11, 21): (1, 0),
    }


# --- it survives the cleanup, and it is private -----------------------------------------------


def test_the_counters_outlive_the_conversations_the_cleanup_deletes(
    make_api, db_session, world
) -> None:
    api = make_api()
    chat(api, "Hello", ip="203.0.113.1")
    bind_tenant(db_session, alpha(world))
    for row in db_session.scalars(select(PublicChatSession)):
        row.updated_at = datetime.now(UTC) - timedelta(days=45)
    db_session.flush()
    gone = service.delete_stale_conversations(
        db_session, datetime.now(UTC), tenant_id=alpha(world), retention_days=30
    )
    assert gone == 1
    assert db_session.scalars(select(PublicChatSession)).all() == []
    assert stats(db_session, alpha(world)) == {TODAY: (1, 0)}, "the number stays, the chat is gone"


def test_the_table_holds_nothing_that_could_identify_a_visitor_or_a_lead() -> None:
    columns = {c.name for c in PublicChatDailyStat.__table__.columns}
    assert columns == {"tenant_id", "day", "conversations_started", "leads_saved", "updated_at"}


def test_one_organisation_never_sees_anothers_numbers(make_api, db_session, world) -> None:
    api = make_api()
    chat(api, "Hello")
    assert stats(db_session, alpha(world)) == {TODAY: (1, 0)}
    assert stats(db_session, beta(world)) == {}


# --- the database keeps it honest -----------------------------------------------------------------


def test_two_increments_add_up_and_never_overwrite_each_other(db_session, world) -> None:
    bind_tenant(db_session, alpha(world))
    repository.count_event(db_session, alpha(world), TODAY, started=1)
    repository.count_event(db_session, alpha(world), TODAY, started=1)
    repository.count_event(db_session, alpha(world), TODAY, leads=1)
    db_session.flush()
    assert stats(db_session, alpha(world)) == {TODAY: (2, 1)}


@pytest.mark.parametrize(
    "sql",
    [
        "update public_chat_daily_stats set conversations_started = conversations_started - 1",
        "update public_chat_daily_stats set leads_saved = 0",
        "update public_chat_daily_stats set conversations_started = -1",
        "delete from public_chat_daily_stats",
    ],
)
def test_the_counters_can_only_grow_and_are_never_deleted(db_session, world, sql: str) -> None:
    bind_tenant(db_session, alpha(world))
    repository.count_event(db_session, alpha(world), TODAY, started=3, leads=2)
    db_session.flush()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text(sql))


def test_the_application_role_can_add_and_raise_but_not_delete_or_empty_the_table(
    db_session,
) -> None:
    def may(privilege: str) -> Any:
        return db_session.scalar(
            text("select has_table_privilege('crm_app', 'public_chat_daily_stats', :p)"),
            {"p": privilege},
        )

    assert may("INSERT") and may("UPDATE") and may("SELECT")
    assert not may("DELETE") and not may("TRUNCATE")
