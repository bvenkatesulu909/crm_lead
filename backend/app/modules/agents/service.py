"""The agent registry: what an organisation allows an AI agent to do (ADR 0016, step AG1).

    check_can_call ─► platform switch ─► agent on? ─► this month's tokens under the budget?
    record_usage   ─► one atomic upsert of the month's counts (+ "80 % reached" flag, once)
    update_settings─► a tenant admin switches, caps or narrows an agent (audited)

A missing settings row means the defaults: on, the default budget, every tool of the catalogue.
The service never commits; the caller does (a request's router, or the AG2 wrapper's request).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish
from app.modules.agents import repository
from app.modules.agents.catalogue import AGENTS, AgentDef
from app.modules.agents.models import MAX_TOKENS, AgentSetting

ENTITY = "agent_settings"
WARN_PERCENT = 80  # admins hear about it when a month's usage first passes this share


class AgentUnavailableError(DomainError):
    status_code = 503
    code = "agent_unavailable"

    def __init__(self) -> None:
        super().__init__("This assistant is not available right now.")


class AgentBudgetReachedError(DomainError):
    status_code = 503
    code = "agent_budget_reached"

    def __init__(self) -> None:
        super().__init__("This assistant has reached its limit for this month.")


class UnknownAgentError(NotFoundError):
    code = "agent_not_found"

    def __init__(self) -> None:
        super().__init__("There is no such AI agent.")


class InvalidAgentSettingError(DomainError):
    status_code = 422
    code = "invalid_agent_setting"


class VersionConflictError(ConflictError):
    code = "version_conflict"

    def __init__(self) -> None:
        super().__init__("The settings were changed by someone else. Reload and try again.")


@dataclass(frozen=True)
class Limits:
    """The platform-wide part of the rules (from the application settings)."""

    platform_disabled: bool
    default_monthly_tokens: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(settings.ai_disabled, settings.agent_default_monthly_tokens)

    @classmethod
    def default(cls) -> "Limits":
        """The rules with no platform switch and the standard budget (for callers without
        application settings, such as the evaluation harness)."""
        default = Settings.model_fields["agent_default_monthly_tokens"].default
        return cls(False, int(default))


@dataclass(frozen=True)
class EffectiveAgent:
    """One agent as one organisation sees it: the catalogue plus its settings plus this month."""

    agent: AgentDef
    enabled: bool
    budget: int
    budget_is_default: bool
    allowed_tools: tuple[str, ...]
    month: date
    input_tokens: int
    output_tokens: int
    calls: int
    version: int | None  # None: no settings row yet

    @property
    def used_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def percent_used(self) -> int:
        return min(999, self.used_tokens * 100 // self.budget)


@dataclass(frozen=True)
class UsageResult:
    used_tokens: int
    crossed_warning: bool  # True exactly once per month and agent


class _Unset:
    """Marks a field the caller does not want to change (None means: back to the default)."""


UNSET = _Unset()


def month_start(now: datetime) -> date:
    moment = now.astimezone(UTC)
    return date(moment.year, moment.month, 1)


def _agent(key: str) -> AgentDef:
    agent = AGENTS.get(key)
    if agent is None:
        raise UnknownAgentError()
    return agent


def _effective(
    agent: AgentDef,
    setting: AgentSetting | None,
    usage_counts: tuple[int, int, int],
    limits: Limits,
    month: date,
) -> EffectiveAgent:
    budget = setting.monthly_token_budget if setting else None
    tools = setting.allowed_tools if setting and setting.allowed_tools is not None else None
    return EffectiveAgent(
        agent=agent,
        enabled=setting.enabled if setting else agent.default_enabled,
        budget=budget if budget is not None else limits.default_monthly_tokens,
        budget_is_default=budget is None,
        # Order and membership follow the catalogue: a tool the code no longer offers is dropped.
        allowed_tools=tuple(t for t in agent.tools if tools is None or t in tools),
        month=month,
        input_tokens=usage_counts[0],
        output_tokens=usage_counts[1],
        calls=usage_counts[2],
        version=setting.version if setting else None,
    )


def effective(
    session: Session, tenant_id: uuid.UUID, key: str, limits: Limits, now: datetime
) -> EffectiveAgent:
    agent = _agent(key)
    month = month_start(now)
    return _effective(
        agent,
        repository.get_setting(session, tenant_id, key),
        repository.usage_counts(session, tenant_id, key, month),
        limits,
        month,
    )


def check_can_call(
    session: Session, tenant_id: uuid.UUID, key: str, limits: Limits, now: datetime
) -> EffectiveAgent:
    """Raise unless this agent may call a model now; otherwise say what it may use."""
    agent = _agent(key)
    # The token budget is about OUR language-model calls; the platform switch stops everything an
    # AI acts through. The web check calls none and answers only to its own on/off switch.
    if limits.platform_disabled and agent.platform_switch:
        raise AgentUnavailableError()
    state = effective(session, tenant_id, key, limits, now)
    if not state.enabled:
        raise AgentUnavailableError()
    if agent.uses_model and state.used_tokens >= state.budget:
        raise AgentBudgetReachedError()
    return state


def record_usage(
    session: Session,
    tenant_id: uuid.UUID,
    key: str,
    *,
    input_tokens: int,
    output_tokens: int,
    limits: Limits,
    now: datetime,
) -> UsageResult:
    """Add one model call to the month's total (atomic) and report the first 80 % crossing."""
    agent = _agent(key)
    month = month_start(now)
    used = repository.add_usage(
        session,
        tenant_id,
        key,
        month,
        max(0, input_tokens),
        max(0, output_tokens),
    )
    if not agent.uses_model:
        return UsageResult(used, False)  # counted as a call; there is no budget to warn about
    setting = repository.get_setting(session, tenant_id, key)
    budget = (
        setting.monthly_token_budget
        if setting and setting.monthly_token_budget is not None
        else limits.default_monthly_tokens
    )
    crossed = used * 100 >= budget * WARN_PERCENT and repository.mark_warned(
        session, tenant_id, key, month, now
    )
    if crossed:
        # Once per month and agent: the organisation's admins hear about it (codes only).
        publish(session, tenant_id, "agent.budget_warning", {"agent": key, "percent": WARN_PERCENT})
    return UsageResult(used, crossed)


def list_agents(
    session: Session, principal: Principal, limits: Limits, now: datetime
) -> list[EffectiveAgent]:
    tenant_id = _tenant(principal, Permission.AGENT_READ)
    return [effective(session, tenant_id, key, limits, now) for key in AGENTS]


def get_agent(
    session: Session, principal: Principal, key: str, limits: Limits, now: datetime
) -> EffectiveAgent:
    tenant_id = _tenant(principal, Permission.AGENT_READ)
    return effective(session, tenant_id, key, limits, now)


def _tenant(principal: Principal, permission: Permission) -> uuid.UUID:
    if (
        principal.tenant_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(permission)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id


def update_settings(
    session: Session,
    principal: Principal,
    key: str,
    *,
    limits: Limits,
    now: datetime,
    version: int | None = None,
    enabled: bool | _Unset = UNSET,
    monthly_token_budget: int | None | _Unset = UNSET,
    allowed_tools: list[str] | None | _Unset = UNSET,
) -> EffectiveAgent:
    """Switch, cap or narrow one agent. ``None`` for the budget or the tools means "default".

    ``version`` is required when the organisation already has settings for the agent (lost
    updates are refused) and must be absent otherwise."""
    tenant_id = _tenant(principal, Permission.AGENT_MANAGE)
    agent = _agent(key)
    if not agent.uses_model and not (
        isinstance(monthly_token_budget, _Unset) and isinstance(allowed_tools, _Unset)
    ):
        raise InvalidAgentSettingError(
            "This feature uses no language model: it has no token budget and no tools to choose."
        )
    if not isinstance(monthly_token_budget, _Unset) and monthly_token_budget is not None:
        if not 1 <= monthly_token_budget <= MAX_TOKENS:
            raise InvalidAgentSettingError(
                f"The budget must be between 1 and {MAX_TOKENS:,} tokens."
            )
    if not isinstance(allowed_tools, _Unset) and allowed_tools is not None:
        unknown = sorted(set(allowed_tools) - set(agent.tools))
        if unknown:
            raise InvalidAgentSettingError(
                f"These tools do not belong to this agent: {', '.join(unknown)}."
            )

    setting = repository.get_setting(session, tenant_id, key, lock=True)
    before = _effective(agent, setting, (0, 0, 0), limits, month_start(now))
    if setting is None:
        if version is not None:
            raise VersionConflictError()
        setting = AgentSetting(tenant_id=tenant_id, agent_key=key, enabled=agent.default_enabled)
        session.add(setting)
    elif version != setting.version:
        raise VersionConflictError()
    else:
        setting.version += 1
    if not isinstance(enabled, _Unset):
        setting.enabled = enabled
    if not isinstance(monthly_token_budget, _Unset):
        setting.monthly_token_budget = monthly_token_budget
    if not isinstance(allowed_tools, _Unset):
        setting.allowed_tools = None if allowed_tools is None else sorted(set(allowed_tools))
    setting.updated_by_user_id = principal.user_id
    session.flush()
    session.refresh(setting)
    after = effective(session, tenant_id, key, limits, now)
    record_audit(
        session,
        principal,
        action="agent.updated",
        entity_type=ENTITY,
        entity_id=setting.id,
        changes=_diff(key, before, after),
    )
    if before.enabled != after.enabled:
        publish(
            session,
            tenant_id,
            "agent.switched",
            {
                "agent": key,
                "state": "on" if after.enabled else "off",
                "actor_id": str(principal.user_id),
            },
        )
    return after


def _diff(key: str, before: EffectiveAgent, after: EffectiveAgent) -> dict[str, Any]:
    return {
        "agent": key,
        "enabled": [before.enabled, after.enabled],
        "monthly_token_budget": [before.budget, after.budget],
        "allowed_tools": [list(before.allowed_tools), list(after.allowed_tools)],
    }
