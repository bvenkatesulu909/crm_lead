"""The fixed part of the agent registry (ADR 0016): the catalogue and the rules around it."""

import re

import pytest

from agent_evals.cases import known_tools
from app.core.auth.rbac import Permission, Role, permissions_for
from app.core.config import Settings
from app.modules.agents.catalogue import AGENTS, KEY_PATTERN
from app.modules.agents.service import Limits
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL


def make_settings(**changes: object) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        **changes,  # type: ignore[arg-type]
    )


def test_the_four_ai_features_are_listed() -> None:
    expected = {"staff_assistant", "portal_assistant", "public_chat", "knowledge_answers"}
    assert set(AGENTS) == expected


def test_every_key_fits_the_database_rule() -> None:
    assert all(re.fullmatch(KEY_PATTERN, key) for key in AGENTS)


@pytest.mark.parametrize("agent", ["staff_assistant", "portal_assistant", "public_chat"])
def test_the_listed_tools_are_exactly_the_tools_the_code_gives(agent: str) -> None:
    """The catalogue cannot drift from the real tools: a new tool must be listed here."""
    assert set(AGENTS[agent].tools) == known_tools(agent)


def test_the_knowledge_answers_use_no_tools() -> None:
    assert AGENTS["knowledge_answers"].tools == ()


def test_every_agent_has_a_description_and_an_owner() -> None:
    for agent in AGENTS.values():
        assert agent.title and agent.description and agent.owner_role == "tenant_admin"


def test_only_tenant_admins_may_change_agents_and_managers_may_read() -> None:
    def can(role: Role, permission: Permission) -> bool:
        return permission in permissions_for(frozenset({role}))

    assert can(Role.TENANT_ADMIN, Permission.AGENT_READ)
    assert can(Role.TENANT_ADMIN, Permission.AGENT_MANAGE)
    assert can(Role.SALES_MANAGER, Permission.AGENT_READ)
    for role in (Role.SALES_MANAGER, Role.SALES_AGENT, Role.SUPPORT_AGENT, Role.CUSTOMER):
        assert not can(role, Permission.AGENT_MANAGE)
    for role in (Role.SALES_AGENT, Role.SUPPORT_AGENT, Role.CUSTOMER, Role.SUPER_ADMIN):
        assert not can(role, Permission.AGENT_READ)


def test_the_default_budget_is_two_million_tokens_and_the_platform_switch_is_off() -> None:
    settings = make_settings()
    assert settings.agent_default_monthly_tokens == 2_000_000 and settings.ai_disabled is False
    limits = Limits.from_settings(settings)
    assert (limits.default_monthly_tokens, limits.platform_disabled) == (2_000_000, False)


@pytest.mark.parametrize("bad", [0, -5, 10_000_000_001])
def test_a_default_budget_outside_the_range_is_refused(bad: int) -> None:
    with pytest.raises(ValueError, match="agent_default_monthly_tokens"):
        make_settings(agent_default_monthly_tokens=bad)
