"""Public interface of the custom agents module (ADR 0034). Other modules import only this.

The agent registry asks ``registry_info`` for an agent key it does not know from its catalogue.
This file imports nothing from the agents module, so the two never import each other.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.custom_agents import repository, rules
from app.modules.custom_agents.service import (
    AgentView,
    CustomAgentNotFoundError,
    InvalidDefinitionError,
    NameTakenError,
    NothingChangedError,
    TooManyAgentsError,
    VersionConflictError,
    archive_agent,
    create_agent,
    get_agent,
    list_agents,
    list_versions,
    update_agent,
)

# The one tool a custom agent's model gets in a run (AB2b); the registry's tool filter lists it.
TOOL_NAME = "submit_suggestion"


@dataclass(frozen=True)
class RegistryInfo:
    """What the agent registry needs to know about one custom agent."""

    key: str
    name: str
    purpose: str


def registry_info(session: Session, tenant_id: uuid.UUID, key: str) -> RegistryInfo | None:
    """The agent behind a registry key, or None: not a custom key, not this organisation's, or
    archived (an archived agent cannot be switched on or run)."""
    if not rules.is_custom_key(key):
        return None
    agent = repository.get_by_key(session, tenant_id, key)
    if agent is None or agent.archived_at is not None:
        return None
    version = repository.get_version(session, tenant_id, agent.id, agent.current_version)
    return RegistryInfo(agent.agent_key, agent.name, version.purpose if version else "")


def registry_infos(session: Session, tenant_id: uuid.UUID) -> list[RegistryInfo]:
    infos: list[RegistryInfo] = []
    for agent in repository.list_agents(session, tenant_id):
        version = repository.get_version(session, tenant_id, agent.id, agent.current_version)
        infos.append(RegistryInfo(agent.agent_key, agent.name, version.purpose if version else ""))
    return infos


__all__ = [
    "TOOL_NAME",
    "AgentView",
    "CustomAgentNotFoundError",
    "InvalidDefinitionError",
    "NameTakenError",
    "NothingChangedError",
    "RegistryInfo",
    "TooManyAgentsError",
    "VersionConflictError",
    "archive_agent",
    "create_agent",
    "get_agent",
    "list_agents",
    "list_versions",
    "registry_info",
    "registry_infos",
    "update_agent",
]
