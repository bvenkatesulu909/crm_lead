# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Batch account research, asking and starting (ADR 0042, BR2): who may, which accounts, what it
may cost, the limits, the two switches, the hard figure the person confirmed, and what is written.
Real database and registry; nothing researches an account yet (that is the worker, BR3)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.errors import ForbiddenError
from app.modules.accounts.models import Account
from app.modules.agents import api as agents_api
from app.modules.agents.models import AgentUsage
from app.modules.deal_desk.models import AccountBrief
from app.modules.research_batches import api as batches_api
from app.modules.research_batches import service
from app.modules.research_batches.models import ResearchBatch, ResearchBatchItem
from app.modules.saved_filters import service as filters_service
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, alpha, principal_for
from tests.db.test_quotes_api import World, world

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
WORST = 8000 + 1024  # input cap + assistant_max_tokens: what one account can use at most


def make_settings(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "database_url": UNREACHABLE_DATABASE_URL,
        "oidc_issuer": TEST_ISSUER,
        "ai_input_price_per_million": Decimal("1"),
        "ai_output_price_per_million": Decimal("2"),
    }
    return Settings(**(values | changes))


def person(world: World, name: str, session: Session):
    principal = principal_for(world.users[name], ROLES[name])
    bind_principal(session, principal)
    return principal


def switch(session: Session, world: World, key: str, on: bool = True, **extra: Any) -> None:
    admin = person(world, "alpha.admin", session)
    current = agents_api.effective(session, alpha(world), key, agents_api.Limits.default(), NOW)
    agents_api.update_settings(
        session,
        admin,
        key,
        limits=agents_api.Limits.default(),
        now=NOW,
        version=current.version,
        enabled=on,
        **extra,
    )
    session.flush()


@pytest.fixture
def ready(db_session: Session, world: World) -> Session:
    """Both switches on, as a tenant administrator would have done."""
    switch(db_session, world, "research_batches")
    switch(db_session, world, "account_research")
    return db_session


def rows(*ids: uuid.UUID, again: bool = False) -> service.BatchRequest:
    return service.BatchRequest(source="rows", account_ids=tuple(ids), research_again=again)


def estimate(session: Session, world: World, request, who="alpha.manager", **settings) -> Any:
    principal = person(world, who, session)
    return service.estimate(session, principal, request, make_settings(**settings), NOW)


def start(session: Session, world: World, request, confirmed, who="alpha.manager", **settings):
    principal = person(world, who, session)
    return service.start(
        session,
        principal,
        request,
        make_settings(**settings),
        confirmed_upper_bound=confirmed,
        now=NOW,
    )


def extra_account(session: Session, world: World, name: str, **fields: Any) -> Account:
    account = Account(tenant_id=alpha(world), name=name, **fields)
    session.add(account)
    session.flush()
    return account


# --- who may, and the two switches ---------------------------------------------------------------


@pytest.mark.parametrize("who", ["alpha.manager", "alpha.admin"])
def test_managers_and_administrators_may_ask(ready, world, who) -> None:
    result = estimate(ready, world, rows(world.ids["A1"], world.ids["A2"]), who)
    assert result.selection.accounts == (world.ids["A1"], world.ids["A2"])


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support", "alpha.customer"])
def test_everyone_else_is_refused(ready, world, who) -> None:
    with pytest.raises(ForbiddenError):
        estimate(ready, world, rows(world.ids["A1"]), who)


def test_a_platform_user_without_an_organisation_is_refused(ready, world) -> None:
    principal = person(world, "alpha.manager", ready)
    stranger = principal.__class__(
        subject="s",
        issuer=principal.issuer,
        user_type="staff",
        roles=principal.roles,
        permissions=principal.permissions,
    )
    with pytest.raises(ForbiddenError):
        service.estimate(ready, stranger, rows(world.ids["A1"]), make_settings(), NOW)


def test_the_batch_feature_is_off_until_switched_on(db_session, world) -> None:
    switch(db_session, world, "account_research")  # research on, batches still off
    with pytest.raises(agents_api.AgentUnavailableError):
        estimate(db_session, world, rows(world.ids["A1"]))


def test_batches_need_account_research_to_be_on_too(db_session, world) -> None:
    switch(db_session, world, "research_batches")  # batches on, research off
    with pytest.raises(agents_api.AgentUnavailableError):
        estimate(db_session, world, rows(world.ids["A1"]))


def test_the_ai_platform_switch_stops_a_batch(ready, world) -> None:
    with pytest.raises(agents_api.AgentUnavailableError):
        estimate(ready, world, rows(world.ids["A1"]), ai_disabled=True)


# --- which accounts --------------------------------------------------------


def test_ids_that_are_not_readable_are_counted_and_never_named(ready, world) -> None:
    made_up = uuid.uuid4()
    result = estimate(
        ready,
        world,
        rows(world.ids["A1"], world.ids["B1"], made_up),  # B1 is beta's
    )
    assert result.selection.accounts == (world.ids["A1"],)
    assert result.selection.not_available == 2


def test_an_archived_account_is_skipped_and_counted_apart(ready, world) -> None:
    old = extra_account(ready, world, "Old Co", deleted_at=NOW)
    result = estimate(ready, world, rows(world.ids["A1"], old.id))
    assert result.selection.accounts == (world.ids["A1"],)
    assert result.selection.archived == 1 and result.selection.not_available == 0


def test_nothing_usable_is_refused(ready, world) -> None:
    with pytest.raises(service.SelectionError) as error:
        estimate(ready, world, rows(world.ids["B1"], uuid.uuid4()))
    assert error.value.code == "empty_selection"


def test_more_than_the_cap_is_refused(ready, world) -> None:
    with pytest.raises(service.SelectionError) as error:
        estimate(ready, world, rows(world.ids["A1"], world.ids["A2"]), research_batch_max=1)
    assert error.value.code == "batch_too_large" and error.value.status_code == 422


def test_a_saved_filter_picks_accounts_as_the_list_would(ready, world) -> None:
    mid = extra_account(ready, world, "Mid Co", segment="mid_market", owner_id=None)
    manager = person(world, "alpha.manager", ready)
    saved = filters_service.create_filter(
        ready, manager, name="Mid", params={"segment": "mid_market"}
    )
    result = estimate(ready, world, service.BatchRequest(source="filter", saved_filter_id=saved.id))
    assert result.selection.accounts == (mid.id,)


def test_a_filter_that_finds_too_many_is_refused_with_the_number(ready, world) -> None:
    manager = person(world, "alpha.manager", ready)
    saved = filters_service.create_filter(
        ready, manager, name="Active", params={"status": "active"}
    )
    with pytest.raises(service.SelectionError) as error:
        estimate(
            ready,
            world,
            service.BatchRequest(source="filter", saved_filter_id=saved.id),
            research_batch_max=1,
        )
    assert error.value.code == "batch_too_large"


def test_someone_elses_private_filter_looks_missing(ready, world) -> None:
    other = person(world, "alpha.manager2", ready)
    private = filters_service.create_filter(
        ready, other, name="Theirs", params={"status": "active"}
    )
    with pytest.raises(Exception) as error:
        estimate(ready, world, service.BatchRequest(source="filter", saved_filter_id=private.id))
    assert getattr(error.value, "code", "") == "saved_filter_not_found"


def test_a_filter_request_without_a_filter_and_an_unknown_source_are_refused(ready, world) -> None:
    for request in (service.BatchRequest(source="filter"), service.BatchRequest(source="magic")):
        with pytest.raises(service.SelectionError):
            estimate(ready, world, request)


# --- reuse -----------------------------------------------------------------


def brief(world: World, key: str, age: timedelta, tokens: tuple[int, int] = (0, 0)) -> AccountBrief:
    return AccountBrief(
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        tenant_id=alpha(world),
        account_id=world.ids[key],
        requested_by_user_id=world.users["alpha.manager"].id,
        sentences=[{"text": "x", "records": [{"type": "account", "id": str(world.ids[key])}]}],
        created_at=NOW - age,
    )


def test_a_brief_under_a_day_old_is_reused_and_costs_nothing(ready, world) -> None:
    fresh = brief(world, "A1", timedelta(hours=2))
    ready.add_all([fresh, brief(world, "A2", timedelta(hours=30))])
    ready.flush()
    result = estimate(ready, world, rows(world.ids["A1"], world.ids["A2"]))
    assert result.reused == ((world.ids["A1"], fresh.id),)
    assert result.accounts_calling_model == 1
    assert result.upper_bound_tokens == WORST


def test_research_again_anyway_does_not_reuse(ready, world) -> None:
    ready.add(brief(world, "A1", timedelta(hours=2)))
    ready.flush()
    result = estimate(ready, world, rows(world.ids["A1"], again=True))
    assert result.reused == () and result.accounts_calling_model == 1


# --- the estimate ----------------------------------------------------------


def test_the_estimate_is_the_upper_bound_with_a_cost_in_decimals(ready, world) -> None:
    result = estimate(ready, world, rows(world.ids["A1"], world.ids["A2"]))
    assert result.upper_bound_tokens == 2 * WORST
    assert result.estimated_cost_usd == Decimal("0.0201")  # (2*8000*1 + 2*1024*2) / 1e6
    assert isinstance(result.estimated_cost_usd, Decimal)
    assert result.typical_tokens == 2 * 3000  # no briefs yet: the built-in default
    assert result.cap_tokens == 2 * WORST


def test_without_a_price_the_cost_is_unknown_not_free(ready, world) -> None:
    result = estimate(
        ready,
        world,
        rows(world.ids["A1"]),
        ai_input_price_per_million=Decimal("0"),
        ai_output_price_per_million=Decimal("0"),
    )
    assert result.estimated_cost_usd is None


def test_the_typical_figure_follows_the_organisations_recent_briefs(ready, world) -> None:
    ready.add(brief(world, "A2", timedelta(days=3), tokens=(1000, 500)))
    ready.flush()
    result = estimate(ready, world, rows(world.ids["A1"]))
    assert result.typical_tokens == 1500  # the average of the last briefs, not the default


def test_the_cap_never_passes_what_the_month_has_left(ready, world) -> None:
    switch(ready, world, "account_research", True, monthly_token_budget=12_000)
    result = estimate(ready, world, rows(world.ids["A1"], world.ids["A2"]))
    assert result.upper_bound_tokens == 2 * WORST and result.monthly_tokens_left == 12_000
    assert result.cap_tokens == 12_000


def test_the_daily_limit_refuses_before_anything_is_queued(ready, world) -> None:
    with pytest.raises(service.DailyLimitError) as error:
        estimate(
            ready,
            world,
            rows(world.ids["A1"], world.ids["A2"]),
            account_research_per_tenant_day=1,
        )
    assert "1 more" in str(error.value) and error.value.status_code == 429


def test_an_estimate_writes_nothing(ready, world) -> None:
    estimate(ready, world, rows(world.ids["A1"]))
    assert ready.scalar(select(func.count()).select_from(ResearchBatch)) == 0
    assert ready.scalar(select(func.count()).select_from(ResearchBatchItem)) == 0


# --- starting --------------------------------------------------------------


def test_start_writes_the_batch_its_frozen_list_and_an_audit_entry(ready, world) -> None:
    batch = start(ready, world, rows(world.ids["A1"], world.ids["A2"]), 2 * WORST)
    assert batch.status == "running" and batch.finished_at is None
    assert batch.account_count == 2 and batch.token_cap == 2 * WORST
    assert batch.estimated_upper_tokens == 2 * WORST and batch.tokens_used == 0
    assert batch.created_by_user_id == world.users["alpha.manager"].id
    assert batch.tenant_id == alpha(world) and batch.source == "rows"
    items = ready.scalars(
        select(ResearchBatchItem).where(ResearchBatchItem.batch_id == batch.id).order_by("position")
    ).all()
    assert [(i.position, i.account_id, i.status) for i in items] == [
        (1, world.ids["A1"], "queued"),
        (2, world.ids["A2"], "queued"),
    ]
    entry = ready.scalars(select(AuditLog).where(AuditLog.action == "research_batch.started")).one()
    assert entry.entity_id == batch.id
    assert entry.changes["accounts"] == 2 and entry.changes["calling_model"] == 2
    assert "Quote A1" not in str(entry.changes)  # ids and counts only, never names


def test_start_counts_one_batch_on_the_agents_page_and_no_tokens(ready, world) -> None:
    start(ready, world, rows(world.ids["A1"]), WORST)
    usage = ready.scalars(
        select(AgentUsage).where(AgentUsage.agent_key == "research_batches")
    ).one()
    assert usage.calls == 1 and usage.input_tokens == 0 and usage.output_tokens == 0


def test_start_queues_no_job_yet(ready, world) -> None:
    from app.core.outbox import OutboxJob

    start(ready, world, rows(world.ids["A1"]), WORST)
    jobs = ready.scalars(select(OutboxJob.kind)).all()
    assert not [kind for kind in jobs if kind.startswith("research_batch")]  # the step is BR3


def test_a_stale_confirmation_is_refused_and_nothing_is_written(ready, world) -> None:
    with pytest.raises(service.EstimateChangedError) as error:
        start(ready, world, rows(world.ids["A1"], world.ids["A2"]), WORST)  # shown for 1, now 2
    assert error.value.status_code == 409 and error.value.code == "estimate_changed"
    assert ready.scalar(select(func.count()).select_from(ResearchBatch)) == 0


def test_a_confirmation_within_twenty_percent_is_accepted(ready, world) -> None:
    start(ready, world, rows(world.ids["A1"]), int(WORST * 1.19))


def test_a_month_budget_too_small_for_one_account_is_refused(ready, world) -> None:
    switch(ready, world, "account_research", True, monthly_token_budget=WORST - 1)
    with pytest.raises(service.BudgetTooSmallError):
        start(ready, world, rows(world.ids["A1"]), WORST)
    assert ready.scalar(select(func.count()).select_from(ResearchBatch)) == 0


def test_the_cap_of_a_started_batch_is_held_to_the_month(ready, world) -> None:
    switch(ready, world, "account_research", True, monthly_token_budget=12_000)
    batch = start(ready, world, rows(world.ids["A1"], world.ids["A2"]), 2 * WORST)
    assert batch.token_cap == 12_000


def test_when_every_brief_is_reused_the_batch_is_finished_at_once(ready, world) -> None:
    first, second = brief(world, "A1", timedelta(hours=1)), brief(world, "A2", timedelta(hours=2))
    ready.add_all([first, second])
    ready.flush()
    batch = start(ready, world, rows(world.ids["A1"], world.ids["A2"]), 0)
    assert batch.status == "finished" and batch.finished_at is not None and batch.token_cap == 0
    items = ready.scalars(
        select(ResearchBatchItem).where(ResearchBatchItem.batch_id == batch.id).order_by("position")
    ).all()
    assert [(i.status, i.brief_id) for i in items] == [("reused", first.id), ("reused", second.id)]


def test_a_filter_batch_remembers_which_filter_but_rows_do_not(ready, world) -> None:
    manager = person(world, "alpha.manager", ready)
    saved = filters_service.create_filter(
        ready, manager, name="All active", params={"status": "active"}
    )
    batch = start(
        ready, world, service.BatchRequest(source="filter", saved_filter_id=saved.id), 2 * WORST
    )
    assert batch.source == "filter" and batch.saved_filter_id == saved.id


# --- limits ----------------------------------------------------------------


def test_one_running_batch_per_person(ready, world) -> None:
    start(ready, world, rows(world.ids["A1"]), WORST)
    with pytest.raises(service.BatchLimitError) as error:
        estimate(ready, world, rows(world.ids["A2"]))
    assert error.value.status_code == 429 and "already have a batch" in str(error.value)


def test_two_running_batches_per_organisation(ready, world) -> None:
    start(ready, world, rows(world.ids["A1"]), WORST, who="alpha.manager")
    start(ready, world, rows(world.ids["A2"]), WORST, who="alpha.manager2")
    with pytest.raises(service.BatchLimitError) as error:
        estimate(ready, world, rows(world.ids["A1"]), who="alpha.admin")
    assert "organisation" in str(error.value)


def test_batches_per_person_per_day(ready, world) -> None:
    start(ready, world, rows(world.ids["A1"]), WORST, research_batch_per_person_day=1)
    ready.execute(update(ResearchBatch).values(status="finished", finished_at=NOW))
    with pytest.raises(service.BatchLimitError) as error:
        estimate(ready, world, rows(world.ids["A2"]), research_batch_per_person_day=1)
    assert "today" in str(error.value)


# --- reading ---------------------------------------------------------------


def test_a_batch_and_its_items_can_be_read_by_managers_of_the_organisation(ready, world) -> None:
    batch = start(ready, world, rows(world.ids["A1"], world.ids["A2"]), 2 * WORST)
    principal = person(world, "alpha.manager2", ready)  # a colleague, not the starter
    found, items = batches_api.get_batch(ready, principal, batch.id)
    assert found.id == batch.id and [i.position for i in items] == [1, 2]
    listing, total = batches_api.list_batches(ready, principal)
    assert [b.id for b in listing] == [batch.id] and total == 1


def test_agents_and_customers_cannot_read_batches(ready, world) -> None:
    batch = start(ready, world, rows(world.ids["A1"]), WORST)
    for who in ("alpha.agent1", "alpha.customer"):
        with pytest.raises(ForbiddenError):
            batches_api.get_batch(ready, person(world, who, ready), batch.id)
        with pytest.raises(ForbiddenError):
            batches_api.list_batches(ready, person(world, who, ready))


def test_another_organisation_cannot_see_a_batch(ready, world) -> None:
    batch = start(ready, world, rows(world.ids["A1"]), WORST)
    switch_beta = person(world, "beta.admin", ready)
    with pytest.raises(batches_api.BatchNotFoundError):
        batches_api.get_batch(ready, switch_beta, batch.id)
    assert batches_api.list_batches(ready, switch_beta) == ([], 0)


def test_a_made_up_batch_is_not_found(ready, world) -> None:
    with pytest.raises(batches_api.BatchNotFoundError):
        batches_api.get_batch(ready, person(world, "alpha.manager", ready), uuid.uuid4())
