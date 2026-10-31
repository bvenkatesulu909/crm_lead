# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""The agent registry (ADR 0016, step AG1) against the real test database.

Defaults, switching, budgets, allowed tools, monthly usage, the 80 % warning, tenant isolation,
role denial and the database's own rules. People come from test_quotes_api.py: tenant alpha has
admin, manager, agent1, support and a customer; tenant beta has admin and agent.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.errors import ForbiddenError
from app.modules.agents import service
from app.modules.agents.catalogue import AGENTS
from app.modules.agents.models import AgentSetting, AgentUsage
from app.modules.agents.service import (
    UNSET,
    AgentBudgetReachedError,
    AgentUnavailableError,
    InvalidAgentSettingError,
    Limits,
    UnknownAgentError,
    VersionConflictError,
)
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
LIMITS = Limits(platform_disabled=False, default_monthly_tokens=1000)
KEY = "staff_assistant"


class Ctx:
    def __init__(self, session: Session, world: World) -> None:
        self.session, self.world = session, world
        self.alpha = world.users["alpha.admin"].tenant_id
        self.beta = world.users["beta.admin"].tenant_id

    def who(self, name: str) -> Any:
        principal = principal_for(self.world.users[name], ROLES[name])
        bind_principal(self.session, principal)
        return principal

    def update(self, name: str = "alpha.admin", key: str = KEY, **changes: Any) -> Any:
        return service.update_settings(
            self.session, self.who(name), key, limits=LIMITS, now=NOW, **changes
        )

    def use(self, tokens: int, tenant: str = "alpha", key: str = KEY, now: datetime = NOW) -> Any:
        tenant_id = self.alpha if tenant == "alpha" else self.beta
        self.who("alpha.admin" if tenant == "alpha" else "beta.admin")
        return service.record_usage(
            self.session,
            tenant_id,
            key,
            input_tokens=tokens // 2,
            output_tokens=tokens - tokens // 2,
            limits=LIMITS,
            now=now,
        )

    def check(self, tenant: str = "alpha", key: str = KEY, limits: Limits = LIMITS) -> Any:
        tenant_id = self.alpha if tenant == "alpha" else self.beta
        self.who("alpha.admin" if tenant == "alpha" else "beta.admin")
        return service.check_can_call(self.session, tenant_id, key, limits, NOW)


@pytest.fixture
def ctx(db_session: Session, world: World) -> Ctx:
    return Ctx(db_session, world)


# --- defaults ---------------------------------------------------------------------------------


def test_without_a_settings_row_an_agent_is_on_with_the_default_budget_and_all_tools(
    ctx: Ctx,
) -> None:
    state = ctx.check()
    assert state.enabled and state.budget == 1000 and state.budget_is_default
    assert state.allowed_tools == AGENTS[KEY].tools
    assert (state.used_tokens, state.calls, state.version) == (0, 0, None)


def test_the_admin_sees_all_four_agents(ctx: Ctx) -> None:
    agents = service.list_agents(ctx.session, ctx.who("alpha.admin"), LIMITS, NOW)
    assert [a.agent.key for a in agents] == list(AGENTS)


def test_a_sales_manager_may_read_but_not_change(ctx: Ctx) -> None:
    assert service.get_agent(ctx.session, ctx.who("alpha.manager"), KEY, LIMITS, NOW).enabled
    with pytest.raises(ForbiddenError):
        ctx.update("alpha.manager", enabled=False)


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support", "alpha.customer"])
def test_others_may_neither_read_nor_change(ctx: Ctx, who: str) -> None:
    with pytest.raises(ForbiddenError):
        service.list_agents(ctx.session, ctx.who(who), LIMITS, NOW)
    with pytest.raises(ForbiddenError):
        ctx.update(who, enabled=False)


def test_an_unknown_agent_is_not_found(ctx: Ctx) -> None:
    with pytest.raises(UnknownAgentError):
        ctx.update(key="no_such_agent", enabled=False)
    with pytest.raises(UnknownAgentError):
        service.get_agent(ctx.session, ctx.who("alpha.admin"), "no_such_agent", LIMITS, NOW)


# --- switching, budgets, tools ----------------------------------------------------------------


def test_an_admin_switches_an_agent_off_and_on(ctx: Ctx) -> None:
    off = ctx.update(enabled=False)
    assert off.enabled is False and off.version == 1
    with pytest.raises(AgentUnavailableError):
        ctx.check()
    on = ctx.update(enabled=True, version=off.version)
    assert on.enabled and on.version == 2
    ctx.check()


def test_switching_one_agent_leaves_the_others_on(ctx: Ctx) -> None:
    ctx.update(enabled=False)
    ctx.check(key="portal_assistant")
    ctx.check(key="public_chat")


def test_a_custom_budget_replaces_the_default_and_none_goes_back(ctx: Ctx) -> None:
    capped = ctx.update(monthly_token_budget=50)
    assert capped.budget == 50 and not capped.budget_is_default
    reset = ctx.update(monthly_token_budget=None, version=capped.version)
    assert reset.budget == 1000 and reset.budget_is_default


@pytest.mark.parametrize("bad", [0, -1, 10_000_000_001])
def test_a_budget_outside_the_range_is_refused(ctx: Ctx, bad: int) -> None:
    with pytest.raises(InvalidAgentSettingError):
        ctx.update(monthly_token_budget=bad)


def test_tools_can_be_narrowed_but_never_added(ctx: Ctx) -> None:
    narrowed = ctx.update(allowed_tools=["search_leads", "get_account"])
    assert narrowed.allowed_tools == ("get_account", "search_leads")  # catalogue order
    with pytest.raises(InvalidAgentSettingError, match="do not belong"):
        ctx.update(allowed_tools=["search_leads", "delete_everything"], version=narrowed.version)
    # a tool of another agent does not count either
    with pytest.raises(InvalidAgentSettingError):
        ctx.update(allowed_tools=["save_lead"], version=narrowed.version)


def test_an_empty_tool_list_means_no_tools_and_none_means_all(ctx: Ctx) -> None:
    none = ctx.update(allowed_tools=[])
    assert none.allowed_tools == ()
    everything = ctx.update(allowed_tools=None, version=none.version)
    assert everything.allowed_tools == AGENTS[KEY].tools


def test_a_field_left_out_is_not_changed(ctx: Ctx) -> None:
    first = ctx.update(monthly_token_budget=77, allowed_tools=["search_leads"])
    second = ctx.update(enabled=False, version=first.version)
    assert (second.budget, second.allowed_tools, second.enabled) == (77, ("search_leads",), False)


def test_a_stale_version_is_refused_and_so_is_a_version_for_a_missing_row(ctx: Ctx) -> None:
    first = ctx.update(enabled=False)
    with pytest.raises(VersionConflictError):
        ctx.update(enabled=True, version=first.version + 5)
    with pytest.raises(VersionConflictError):
        ctx.update(enabled=True)  # a row exists now: the version is required
    with pytest.raises(VersionConflictError):
        ctx.update(key="public_chat", enabled=False, version=3)  # no row there yet


def test_every_change_is_audited_with_before_and_after(ctx: Ctx) -> None:
    ctx.update(enabled=False, monthly_token_budget=500)
    ctx.session.flush()
    row = ctx.session.scalars(
        select(AuditLog).where(AuditLog.action == "agent.updated", AuditLog.tenant_id == ctx.alpha)
    ).one()
    assert row.actor_user_id == ctx.world.users["alpha.admin"].id
    assert row.changes["agent"] == KEY
    assert row.changes["enabled"] == [True, False] and row.changes["monthly_token_budget"] == [
        1000,
        500,
    ]


def test_the_row_records_who_changed_it(ctx: Ctx) -> None:
    ctx.update(enabled=False)
    setting = ctx.session.scalars(
        select(AgentSetting).where(AgentSetting.tenant_id == ctx.alpha)
    ).one()
    assert setting.updated_by_user_id == ctx.world.users["alpha.admin"].id


# --- the platform switch and the budget gate --------------------------------------------------


def test_the_platform_switch_refuses_everything_even_without_settings(ctx: Ctx) -> None:
    off = Limits(platform_disabled=True, default_monthly_tokens=1000)
    for key, agent in AGENTS.items():
        if not agent.uses_model:
            ctx.check(key=key, limits=off)  # the AI switch is about models; the web check has none
            continue
        with pytest.raises(AgentUnavailableError):
            ctx.check(key=key, limits=off)
    with pytest.raises(AgentUnavailableError):
        ctx.check(tenant="beta", limits=off)


def test_usage_below_the_budget_is_allowed_and_at_the_budget_is_not(ctx: Ctx) -> None:
    ctx.use(999)
    ctx.check()  # 999 of 1000
    ctx.use(1)
    with pytest.raises(AgentBudgetReachedError):
        ctx.check()  # exactly at the cap


def test_over_the_budget_is_refused_with_its_own_code(ctx: Ctx) -> None:
    ctx.use(5000)
    with pytest.raises(AgentBudgetReachedError) as caught:
        ctx.check()
    assert caught.value.code == "agent_budget_reached" and caught.value.status_code == 503


def test_raising_the_budget_lets_the_agent_work_again(ctx: Ctx) -> None:
    ctx.use(1000)
    with pytest.raises(AgentBudgetReachedError):
        ctx.check()
    ctx.update(monthly_token_budget=5000)
    assert ctx.check().used_tokens == 1000


def test_a_disabled_agent_says_unavailable_not_over_budget(ctx: Ctx) -> None:
    ctx.use(5000)
    ctx.update(enabled=False)
    with pytest.raises(AgentUnavailableError):
        ctx.check()


def test_a_new_month_starts_at_zero(ctx: Ctx) -> None:
    ctx.use(5000)
    next_month = NOW.replace(month=11, day=1, hour=0)
    ctx.who("alpha.admin")
    state = service.check_can_call(ctx.session, ctx.alpha, KEY, LIMITS, next_month)
    assert state.used_tokens == 0 and state.month.isoformat() == "2026-11-01"


def test_the_month_is_cut_in_utc(ctx: Ctx) -> None:
    from datetime import timezone

    late = datetime(2026, 10, 31, 23, 30, tzinfo=timezone(timedelta(hours=-5)))  # 04:30 UTC, Nov 1
    assert service.month_start(late).isoformat() == "2026-11-01"


# --- usage ------------------------------------------------------------------------------------


def test_usage_adds_up_per_month_and_counts_calls(ctx: Ctx) -> None:
    ctx.use(100)
    ctx.use(250)
    state = service.effective(ctx.session, ctx.alpha, KEY, LIMITS, NOW)
    assert (state.used_tokens, state.calls) == (350, 2)
    assert state.input_tokens + state.output_tokens == 350


def test_usage_is_kept_per_agent_and_per_organisation(ctx: Ctx) -> None:
    ctx.use(100)
    ctx.use(40, key="public_chat")
    ctx.use(999, tenant="beta")
    ctx.who("alpha.admin")
    assert service.effective(ctx.session, ctx.alpha, KEY, LIMITS, NOW).used_tokens == 100
    assert service.effective(ctx.session, ctx.alpha, "public_chat", LIMITS, NOW).used_tokens == 40
    ctx.who("beta.admin")
    assert service.effective(ctx.session, ctx.beta, KEY, LIMITS, NOW).used_tokens == 999


def test_negative_token_counts_are_treated_as_zero(ctx: Ctx) -> None:
    ctx.who("alpha.admin")
    service.record_usage(
        ctx.session, ctx.alpha, KEY, input_tokens=-5, output_tokens=7, limits=LIMITS, now=NOW
    )
    assert service.effective(ctx.session, ctx.alpha, KEY, LIMITS, NOW).used_tokens == 7


def test_usage_for_an_unknown_agent_is_refused(ctx: Ctx) -> None:
    ctx.who("alpha.admin")
    with pytest.raises(UnknownAgentError):
        service.record_usage(
            ctx.session, ctx.alpha, "nope", input_tokens=1, output_tokens=1, limits=LIMITS, now=NOW
        )


def test_the_warning_is_reported_once_when_80_percent_is_passed(ctx: Ctx) -> None:
    assert ctx.use(700).crossed_warning is False
    assert ctx.use(100).crossed_warning is True  # 800 of 1000
    assert ctx.use(50).crossed_warning is False  # already told
    assert ctx.use(10).crossed_warning is False


def test_the_warning_uses_the_organisations_own_budget(ctx: Ctx) -> None:
    ctx.update(monthly_token_budget=100)
    assert ctx.use(79).crossed_warning is False
    assert ctx.use(1).crossed_warning is True


def test_the_warning_comes_again_in_the_next_month(ctx: Ctx) -> None:
    assert ctx.use(900).crossed_warning is True
    november = NOW.replace(month=11)
    assert ctx.use(900, now=november).crossed_warning is True


def test_adding_usage_is_one_atomic_statement(ctx: Ctx) -> None:
    """Counts are added inside the database (ON CONFLICT DO UPDATE ... = column + n), never read,
    changed in Python and written back, so parallel calls cannot overwrite each other."""
    from sqlalchemy import event

    seen: list[str] = []
    engine = ctx.session.get_bind()
    event.listen(engine, "before_cursor_execute", lambda c, cur, stmt, *a: seen.append(stmt))
    ctx.use(3)
    ctx.use(4)
    inserts = [q for q in seen if "INSERT INTO agent_usage" in q]
    assert len(inserts) == 2
    assert all("ON CONFLICT" in q and "agent_usage.input_tokens +" in q for q in inserts)
    assert not [q for q in seen if q.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in q]


# --- tenant isolation and the database's own rules --------------------------------------------


def test_another_organisation_neither_sees_nor_inherits_the_settings(ctx: Ctx) -> None:
    ctx.update(enabled=False, monthly_token_budget=5)
    ctx.use(100)
    ctx.who("beta.admin")
    state = service.effective(ctx.session, ctx.beta, KEY, LIMITS, NOW)
    assert state.enabled and state.budget == 1000 and state.used_tokens == 0
    visible = ctx.session.scalars(select(AgentSetting)).all()
    assert visible == []  # row-level security hides alpha's row from beta's context
    assert ctx.session.scalars(select(AgentUsage)).all() == []


def test_an_admin_cannot_change_another_organisations_agent(ctx: Ctx) -> None:
    ctx.update("alpha.admin", enabled=False)
    beta = ctx.update("beta.admin", enabled=True)  # beta's own, separate row
    assert beta.version == 1
    ctx.who("beta.admin")
    assert service.effective(ctx.session, ctx.beta, KEY, LIMITS, NOW).enabled


def test_the_database_refuses_a_bad_key_a_bad_budget_and_a_second_row(ctx: Ctx) -> None:
    ctx.who("alpha.admin")
    for bad in (
        AgentSetting(tenant_id=ctx.alpha, agent_key="Bad Key"),
        AgentSetting(tenant_id=ctx.alpha, agent_key=KEY, monthly_token_budget=0),
    ):
        with pytest.raises(IntegrityError), ctx.session.begin_nested():
            ctx.session.add(bad)
            ctx.session.flush()
    ctx.session.add(AgentSetting(tenant_id=ctx.alpha, agent_key=KEY))
    ctx.session.flush()
    with pytest.raises(IntegrityError), ctx.session.begin_nested():
        ctx.session.add(AgentSetting(tenant_id=ctx.alpha, agent_key=KEY))
        ctx.session.flush()


def test_the_database_refuses_negative_counts_and_a_mid_month_date(ctx: Ctx) -> None:
    ctx.who("alpha.admin")
    for bad in (
        AgentUsage(tenant_id=ctx.alpha, agent_key=KEY, month=NOW.date().replace(day=1), calls=-1),
        AgentUsage(tenant_id=ctx.alpha, agent_key=KEY, month=NOW.date()),
    ):
        with pytest.raises(IntegrityError), ctx.session.begin_nested():
            ctx.session.add(bad)
            ctx.session.flush()


def test_usage_rows_cannot_be_deleted_by_the_application_role(ctx: Ctx) -> None:
    ctx.use(10)
    with pytest.raises(DBAPIError), ctx.session.begin_nested():
        ctx.session.execute(text("DELETE FROM agent_usage"))


def test_only_a_user_of_the_same_organisation_can_be_the_updater(ctx: Ctx) -> None:
    ctx.who("alpha.admin")
    foreign = ctx.world.users["beta.admin"].id
    with pytest.raises(IntegrityError), ctx.session.begin_nested():
        ctx.session.add(
            AgentSetting(tenant_id=ctx.alpha, agent_key=KEY, updated_by_user_id=foreign)
        )
        ctx.session.flush()


def test_unset_is_a_distinct_marker() -> None:
    assert UNSET is not None and not isinstance(None, type(UNSET))
