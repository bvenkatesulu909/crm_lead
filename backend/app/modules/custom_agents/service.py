"""Defining custom agents (ADR 0034, AB2a): create, change (a new version), archive, read.

An administrator writes the definition; every change is a new insert-only version and an audit
entry (ids, version numbers and codes - never the instruction text). The service never commits;
the caller does. Running an agent is a separate file (AB2b): nothing here calls a model.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.custom_agents import repository, rules
from app.modules.custom_agents.models import CustomAgent, CustomAgentVersion

ENTITY = "custom_agent"


class CustomAgentNotFoundError(NotFoundError):
    code = "custom_agent_not_found"

    def __init__(self) -> None:
        # The same answer for an agent that does not exist and for another organisation's.
        super().__init__("There is no such custom agent.")


class InvalidDefinitionError(DomainError):
    status_code = 422
    code = "invalid_custom_agent"


class NameTakenError(ConflictError):
    code = "custom_agent_name_taken"

    def __init__(self) -> None:
        super().__init__("Another custom agent already has this name.")


class TooManyAgentsError(ConflictError):
    code = "custom_agent_limit"

    def __init__(self) -> None:
        super().__init__(f"An organisation can have at most {rules.MAX_AGENTS} custom agents.")


class VersionConflictError(ConflictError):
    code = "version_conflict"

    def __init__(self) -> None:
        super().__init__("The agent was changed by someone else. Reload it and try again.")


class NothingChangedError(DomainError):
    status_code = 422
    code = "custom_agent_unchanged"

    def __init__(self) -> None:
        super().__init__("Nothing was changed, so no new version was made.")


@dataclass(frozen=True)
class AgentView:
    """An agent and the version it currently runs."""

    agent: CustomAgent
    current: CustomAgentVersion


def _tenant(principal: Principal, *permissions: Permission) -> uuid.UUID:
    """The organisation of a staff member who holds at least one of the permissions."""
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not any(principal.has_permission(p) for p in permissions)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id


def _user(principal: Principal) -> uuid.UUID:
    if principal.user_id is None:  # _tenant already refused a principal without one
        raise ForbiddenError("You may not do this.")
    return principal.user_id


def _clean(
    *, name: str, purpose: str, instruction: str, read_sets: list[str], suggestion_kinds: list[str]
) -> rules.CleanDefinition:
    try:
        return rules.clean_definition(
            name=name,
            purpose=purpose,
            instruction=instruction,
            read_sets=read_sets,
            suggestion_kinds=suggestion_kinds,
        )
    except rules.DefinitionError as problem:
        raise InvalidDefinitionError(str(problem)) from None


def _current(session: Session, tenant_id: uuid.UUID, agent: CustomAgent) -> CustomAgentVersion:
    version = repository.get_version(session, tenant_id, agent.id, agent.current_version)
    if version is None:  # cannot happen: the two are written together
        raise CustomAgentNotFoundError()
    return version


def _audit(
    session: Session,
    principal: Principal,
    action: str,
    agent: CustomAgent,
    version: CustomAgentVersion | None,
    definition: rules.CleanDefinition | None,
) -> None:
    changes: dict[str, object] = {"agent_key": agent.agent_key}
    if version is not None and definition is not None:
        changes |= {
            "version_no": version.version_no,
            "record_type": definition.record_type,
            "read_sets": list(version.read_sets),
            "suggestion_kinds": list(version.suggestion_kinds),
            "cleaned": list(definition.cleaned),
        }
    record_audit(
        session, principal, action=action, entity_type=ENTITY, entity_id=agent.id, changes=changes
    )


def _new_version(
    principal: Principal,
    agent: CustomAgent,
    number: int,
    definition: rules.CleanDefinition,
) -> CustomAgentVersion:
    return CustomAgentVersion(
        tenant_id=agent.tenant_id,
        custom_agent_id=agent.id,
        version_no=number,
        purpose=definition.purpose,
        instruction=definition.instruction,
        read_sets=definition.read_sets,
        suggestion_kinds=definition.suggestion_kinds,
        cleaned=definition.cleaned,
        created_by_user_id=_user(principal),
    )


def create_agent(
    session: Session,
    principal: Principal,
    *,
    name: str,
    purpose: str,
    instruction: str,
    read_sets: list[str],
    suggestion_kinds: list[str],
) -> AgentView:
    """A new agent with its first version. It starts switched off in the registry."""
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE)
    definition = _clean(
        name=name,
        purpose=purpose,
        instruction=instruction,
        read_sets=read_sets,
        suggestion_kinds=suggestion_kinds,
    )
    if repository.count_active(session, tenant_id) >= rules.MAX_AGENTS:
        raise TooManyAgentsError()
    if repository.name_taken(session, tenant_id, definition.name):
        raise NameTakenError()
    agent = CustomAgent(
        tenant_id=tenant_id,
        name=definition.name,
        current_version=1,
        created_by_user_id=_user(principal),
    )
    session.add(agent)
    session.flush()
    version = _new_version(principal, agent, 1, definition)
    session.add(version)
    session.flush()
    _audit(session, principal, "custom_agent.created", agent, version, definition)
    return AgentView(agent, version)


def update_agent(
    session: Session,
    principal: Principal,
    agent_id: uuid.UUID,
    *,
    version: int,
    name: str,
    purpose: str,
    instruction: str,
    read_sets: list[str],
    suggestion_kinds: list[str],
) -> AgentView:
    """Save a changed definition as the next version. ``version`` is the agent's version counter
    as the editor last saw it (a lost update is refused). Older versions are kept."""
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE)
    agent = repository.get(session, tenant_id, agent_id, lock=True)
    if agent is None or agent.archived_at is not None:
        raise CustomAgentNotFoundError()
    if agent.version != version:
        raise VersionConflictError()
    definition = _clean(
        name=name,
        purpose=purpose,
        instruction=instruction,
        read_sets=read_sets,
        suggestion_kinds=suggestion_kinds,
    )
    if repository.name_taken(session, tenant_id, definition.name, except_id=agent.id):
        raise NameTakenError()
    current = _current(session, tenant_id, agent)
    same = (
        definition.name == agent.name
        and definition.purpose == current.purpose
        and definition.instruction == current.instruction
        and definition.read_sets == list(current.read_sets)
        and definition.suggestion_kinds == list(current.suggestion_kinds)
    )
    if same:
        raise NothingChangedError()
    new = _new_version(principal, agent, agent.current_version + 1, definition)
    session.add(new)
    agent.name = definition.name
    agent.current_version = new.version_no
    session.flush()
    _audit(session, principal, "custom_agent.updated", agent, new, definition)
    return AgentView(agent, new)


def archive_agent(
    session: Session,
    principal: Principal,
    agent_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CustomAgent:
    """Retire an agent: it cannot be run or edited, its history and usage stay."""
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE)
    agent = repository.get(session, tenant_id, agent_id, lock=True)
    if agent is None or agent.archived_at is not None:
        raise CustomAgentNotFoundError()
    agent.archived_at = now or datetime.now(UTC)
    session.flush()
    _audit(session, principal, "custom_agent.archived", agent, None, None)
    return agent


def get_agent(session: Session, principal: Principal, agent_id: uuid.UUID) -> AgentView:
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE, Permission.CUSTOM_AGENT_RUN)
    agent = repository.get(session, tenant_id, agent_id)
    if agent is None or agent.archived_at is not None:
        raise CustomAgentNotFoundError()
    return AgentView(agent, _current(session, tenant_id, agent))


def list_agents(session: Session, principal: Principal) -> list[AgentView]:
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE, Permission.CUSTOM_AGENT_RUN)
    return [
        AgentView(agent, _current(session, tenant_id, agent))
        for agent in repository.list_agents(session, tenant_id)
    ]


def list_versions(
    session: Session, principal: Principal, agent_id: uuid.UUID
) -> list[CustomAgentVersion]:
    """The whole history of one agent, newest first - for administrators only."""
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE)
    agent = repository.get(session, tenant_id, agent_id)
    if agent is None:
        raise CustomAgentNotFoundError()
    return repository.list_versions(session, tenant_id, agent.id)
