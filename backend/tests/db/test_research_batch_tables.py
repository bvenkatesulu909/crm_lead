# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Tables of batch account research (ADR 0042, BR1): the checks the database itself enforces, the
locks on what a batch may not change afterwards, row-level security, and the overview functions
the batch will use (newest brief per account, a summary of a stored brief)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.deal_desk import api as deal_desk_api
from app.modules.deal_desk.models import AccountBrief
from app.modules.research_batches.models import ResearchBatch, ResearchBatchItem
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, alpha, principal_for
from tests.db.test_quotes_api import World, world


def batch(world: World, **changes: Any) -> ResearchBatch:
    values: dict[str, Any] = {
        "tenant_id": alpha(world),
        "created_by_user_id": world.users["alpha.manager"].id,
        "source": "rows",
        "account_count": 2,
        "estimated_upper_tokens": 20_000,
        "token_cap": 20_000,
    }
    return ResearchBatch(**(values | changes))


def item(world: World, parent: ResearchBatch, key: str, pos: int, **changes: Any):
    values: dict[str, Any] = {
        "tenant_id": alpha(world),
        "batch_id": parent.id,
        "position": pos,
        "account_id": world.ids[key],
    }
    return ResearchBatchItem(**(values | changes))


@pytest.fixture
def session(db_session: Session, world: World) -> Session:
    bind_tenant(db_session, alpha(world))
    return db_session


def refused(session: Session, work: Any) -> None:
    """The database refuses this, and only this statement is undone."""
    nested = session.begin_nested()
    with pytest.raises(DBAPIError):
        work()
        session.flush()
    nested.rollback()


def brief(world: World, key: str, **changes: Any) -> AccountBrief:
    values: dict[str, Any] = {
        "tenant_id": alpha(world),
        "account_id": world.ids[key],
        "requested_by_user_id": world.users["alpha.manager"].id,
        "sentences": [
            {
                "text": "One open deal.",
                "records": [{"type": "opportunity", "id": str(uuid.uuid4())}],
            },
            {
                "text": "Health is fine.",
                "records": [{"type": "account", "id": str(world.ids[key])}],
            },
        ],
        "gathered": {"sales": 2, "service": 0},
        "dropped": 1,
        "input_tokens": 300,
        "output_tokens": 120,
    }
    return AccountBrief(**(values | changes))


# --- what the database refuses -------------------------------------------------------------------


def test_a_batch_and_its_items_can_be_stored_and_read_back(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    session.add_all([item(world, parent, "A1", 1), item(world, parent, "A2", 2)])
    session.flush()
    assert parent.status == "running" and parent.finished_at is None and parent.version == 1
    assert parent.tokens_used == 0 and parent.cancel_requested is False
    assert [i.status for i in session.query(ResearchBatchItem).order_by("position")] == [
        "queued",
        "queued",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"account_count": 0},
        {"account_count": 101},
        {"status": "paused"},
        {"source": "magic"},
        {"token_cap": -1},
        {"estimated_upper_tokens": -1},
        {"tokens_used": -1},
        {"status": "finished"},  # a finished batch needs its finished_at
    ],
)
def test_bad_batches_are_refused(session, world, changes) -> None:
    refused(session, lambda: session.add(batch(world, **changes)))


def test_a_running_batch_has_no_finish_time_and_an_ended_one_has(session, world) -> None:
    refused(session, lambda: session.add(batch(world, finished_at=datetime.now(UTC))))
    ended = batch(world, status="cancelled", finished_at=datetime.now(UTC))
    session.add(ended)
    session.flush()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unknown"},
        {"position": 0},
        {"position": 101},
        {"status": "failed"},  # a failed item names why
        {"status": "failed", "failure_code": "because"},
        {"failure_code": "error"},  # only a failed item has a reason
        {"status": "done"},  # a finished item points at its brief
        {"brief_id": uuid.uuid4()},  # and only a finished one does
        {"input_tokens": -1},
    ],
)
def test_bad_items_are_refused(session, world, changes) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    refused(session, lambda: session.add(item(world, parent, "A1", 1, **changes)))


def test_failed_done_and_reused_items_are_accepted_with_what_they_need(session, world) -> None:
    parent = batch(world, account_count=3)
    session.add(parent)
    session.flush()
    session.add_all(
        [
            item(world, parent, "A1", 1, status="failed", failure_code="over_budget"),
            item(world, parent, "A2", 2, status="done", brief_id=uuid.uuid4()),
        ]
    )
    session.flush()


def test_an_account_and_a_position_appear_once_per_batch(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    session.add(item(world, parent, "A1", 1))
    session.flush()
    refused(session, lambda: session.add(item(world, parent, "A1", 2)))  # same account
    refused(session, lambda: session.add(item(world, parent, "A2", 1)))  # same position


def test_an_item_needs_an_account_and_a_batch_of_the_same_organisation(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    refused(session, lambda: session.add(item(world, parent, "B1", 1)))  # beta's account
    refused(
        session,
        lambda: session.add(
            ResearchBatchItem(
                tenant_id=alpha(world),
                batch_id=uuid.uuid4(),
                position=1,
                account_id=world.ids["A1"],
            )
        ),
    )


# --- what a batch may not change afterwards -------------------------------------------------


@pytest.mark.parametrize(
    "assignment",
    [
        "token_cap = token_cap + 1",
        "estimated_upper_tokens = 1",
        "account_count = 1",
        "not_available_count = 5",
        "archived_count = 5",
        "source = 'filter'",
        "research_again = true",
        "created_by_user_id = '00000000-0000-0000-0000-000000000001'",
        "created_at = created_at - interval '1 day'",
        "saved_filter_id = '00000000-0000-0000-0000-000000000001'",
        "estimated_cost_usd = 9",
    ],
)
def test_the_terms_of_a_batch_cannot_change(session, world, assignment) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    refused(
        session,
        lambda: session.execute(
            text(f"UPDATE research_batches SET {assignment} WHERE id = :id"),  # noqa: S608
            {"id": parent.id},
        ),
    )


def test_progress_can_move_forward_but_tokens_never_back(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    session.execute(
        text(
            "UPDATE research_batches SET tokens_used = 500, cancel_requested = true WHERE id = :id"
        ),
        {"id": parent.id},
    )
    refused(
        session,
        lambda: session.execute(
            text("UPDATE research_batches SET tokens_used = 100 WHERE id = :id"), {"id": parent.id}
        ),
    )


def test_a_finished_batch_cannot_come_back_to_life(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    session.execute(
        text("UPDATE research_batches SET status = 'finished', finished_at = now() WHERE id = :id"),
        {"id": parent.id},
    )
    refused(
        session,
        lambda: session.execute(
            text(
                "UPDATE research_batches SET status = 'running', finished_at = NULL WHERE id = :id"
            ),
            {"id": parent.id},
        ),
    )


def test_an_item_keeps_its_place_and_an_ended_item_its_state(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    first = item(world, parent, "A1", 1)
    session.add(first)
    session.flush()
    for assignment in (
        "position = 2",
        "account_id = '00000000-0000-0000-0000-000000000001'",
        "batch_id = '00000000-0000-0000-0000-000000000001'",
    ):
        refused(
            session,
            lambda a=assignment: session.execute(
                text(f"UPDATE research_batch_items SET {a} WHERE id = :id"),  # noqa: S608
                {"id": first.id},
            ),
        )
    session.execute(
        text("UPDATE research_batch_items SET status = 'running' WHERE id = :id"), {"id": first.id}
    )
    session.execute(
        text(
            "UPDATE research_batch_items SET status = 'failed', failure_code = 'error' "
            "WHERE id = :id"
        ),
        {"id": first.id},
    )
    refused(
        session,
        lambda: session.execute(
            text(
                "UPDATE research_batch_items SET status = 'queued', failure_code = NULL "
                "WHERE id = :id"
            ),
            {"id": first.id},
        ),
    )


def test_rows_are_kept_for_a_year_and_cannot_be_truncated(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    session.add(item(world, parent, "A1", 1))
    session.flush()
    for statement in (
        "DELETE FROM research_batch_items",
        "DELETE FROM research_batches",
        "TRUNCATE research_batch_items",
        "TRUNCATE research_batches",
    ):
        refused(session, lambda s=statement: session.execute(text(s)))


# --- row-level security --------------------------------------------------------------------------


def test_another_organisation_sees_none_of_it(session, world) -> None:
    parent = batch(world)
    session.add(parent)
    session.flush()
    session.add(item(world, parent, "A1", 1))
    session.flush()
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(session, beta)
    for table in ("research_batches", "research_batch_items"):
        query = text(f"SELECT count(*) FROM {table}")  # noqa: S608
        assert session.execute(query).scalar() == 0
    refused(
        session,
        lambda: session.add(
            ResearchBatch(
                tenant_id=alpha(world),  # writing into another organisation is refused
                created_by_user_id=world.users["alpha.manager"].id,
                source="rows",
                account_count=1,
                estimated_upper_tokens=1,
                token_cap=1,
            )
        ),
    )


# --- the overview functions ----------------------------------------------------------------------


def test_the_overview_summarises_a_brief_without_its_text(session, world) -> None:
    stored = brief(world, "A1")
    session.add(stored)
    session.flush()
    manager = principal_for(world.users["alpha.manager"], ROLES["alpha.manager"])
    bind_principal(session, manager)
    found = deal_desk_api.overviews_of(session, manager, [stored.id])[stored.id]
    assert found.sentences == 2 and found.dropped == 1 and found.tokens == 420
    assert found.gathered == {"sales": 2, "service": 0}
    assert found.account_id == world.ids["A1"]
    assert not hasattr(found, "text") and "One open deal" not in repr(found)


def test_the_newest_brief_of_each_account_is_found(session, world) -> None:
    old = brief(world, "A1", created_at=datetime.now(UTC) - timedelta(days=3))
    session.add(old)
    session.flush()
    new = brief(world, "A1", sentences=[], dropped=0)
    other = brief(world, "A2")
    session.add_all([new, other])
    session.flush()
    manager = principal_for(world.users["alpha.manager"], ROLES["alpha.manager"])
    bind_principal(session, manager)
    found = deal_desk_api.latest_overviews(session, manager, [world.ids["A1"], world.ids["A2"]])
    assert found[world.ids["A1"]].brief_id == new.id
    assert found[world.ids["A2"]].brief_id == other.id
    assert deal_desk_api.latest_overviews(session, manager, []) == {}


def test_an_account_the_person_may_not_read_has_no_overview(session, world) -> None:
    mine, theirs = brief(world, "A1"), brief(world, "A2")
    session.add_all([mine, theirs])
    session.flush()
    agent = principal_for(world.users["alpha.agent1"], ROLES["alpha.agent1"])  # owns A1 only
    bind_principal(session, agent)
    found = deal_desk_api.latest_overviews(session, agent, [world.ids["A1"], world.ids["A2"]])
    assert set(found) == {world.ids["A1"]}
    assert set(deal_desk_api.overviews_of(session, agent, [mine.id, theirs.id])) == {mine.id}


def test_another_organisation_and_customers_get_nothing(session, world) -> None:
    stored = brief(world, "A1")
    session.add(stored)
    session.flush()
    stranger = principal_for(world.users["beta.admin"], ROLES["beta.admin"])
    bind_principal(session, stranger)
    assert deal_desk_api.latest_overviews(session, stranger, [world.ids["A1"]]) == {}
    assert deal_desk_api.overviews_of(session, stranger, [stored.id]) == {}
    customer = principal_for(world.users["alpha.customer"], ROLES["alpha.customer"])
    bind_principal(session, customer)
    assert deal_desk_api.latest_overviews(session, customer, [world.ids["A1"]]) == {}
    assert deal_desk_api.overviews_of(session, customer, [stored.id]) == {}
