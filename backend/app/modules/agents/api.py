"""Public interface of the agents module (ADR 0016). Other modules import only this."""

from app.modules.agents.catalogue import AGENTS, AgentDef
from app.modules.agents.governed import GovernedModel, governed
from app.modules.agents.service import (
    UNSET,
    AgentBudgetReachedError,
    AgentUnavailableError,
    EffectiveAgent,
    Limits,
    UsageResult,
    check_can_call,
    effective,
    get_agent,
    list_agents,
    record_usage,
    update_settings,
)

__all__ = [
    "AGENTS",
    "UNSET",
    "AgentBudgetReachedError",
    "AgentDef",
    "AgentUnavailableError",
    "EffectiveAgent",
    "GovernedModel",
    "Limits",
    "UsageResult",
    "check_can_call",
    "effective",
    "governed",
    "get_agent",
    "list_agents",
    "record_usage",
    "update_settings",
]
