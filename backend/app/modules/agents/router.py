"""/api/v1/agents - the registry of the CRM's AI agents (ADR 0016).

Thin layer: permissions, then the service; the write endpoint commits once. Tenant admins
change, sales managers (and admins) read, everyone else is refused.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import service
from app.modules.agents.schemas import AgentPage, AgentRead, AgentUpdate
from app.modules.agents.service import UNSET, EffectiveAgent, Limits
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/agents", tags=["agents"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.AGENT_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.AGENT_MANAGE))]


def _limits(request: Request) -> Limits:
    return Limits.from_settings(request.app.state.settings)


def _now() -> datetime:
    return datetime.now(UTC)


def _read(state: EffectiveAgent) -> AgentRead:
    return AgentRead(
        key=state.agent.key,
        title=state.agent.title,
        description=state.agent.description,
        owner_role=state.agent.owner_role,
        enabled=state.enabled,
        monthly_token_budget=state.budget,
        budget_is_default=state.budget_is_default,
        allowed_tools=list(state.allowed_tools),
        all_tools=list(state.agent.tools),
        month=state.month,
        input_tokens=state.input_tokens,
        output_tokens=state.output_tokens,
        used_tokens=state.used_tokens,
        calls=state.calls,
        percent_used=state.percent_used,
        version=state.version,
    )


@router.get(
    "",
    summary="The AI agents of your organisation: switch, budget, tools and this month's usage",
    responses=problem_responses(401, 403),
)
def list_agents(principal: Reader, session: Db, request: Request) -> AgentPage:
    states = service.list_agents(session, principal, _limits(request), _now())
    return AgentPage(items=[_read(state) for state in states])


@router.get("/{key}", summary="One AI agent", responses=problem_responses(401, 403, 404))
def get_agent(key: str, principal: Reader, session: Db, request: Request) -> AgentRead:
    return _read(service.get_agent(session, principal, key, _limits(request), _now()))


@router.patch(
    "/{key}",
    summary="Switch an AI agent on or off, set its monthly token budget, narrow its tools",
    description="Only the fields you send are changed; null for the budget or the tools means "
    "the default. Send the `version` you read once the agent has settings (otherwise omit it).",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def update_agent(
    key: str, data: AgentUpdate, principal: Manager, session: Db, request: Request
) -> AgentRead:
    sent = data.model_fields_set
    state = service.update_settings(
        session,
        principal,
        key,
        limits=_limits(request),
        now=_now(),
        version=data.version,
        enabled=data.enabled if "enabled" in sent and data.enabled is not None else UNSET,
        monthly_token_budget=data.monthly_token_budget if "monthly_token_budget" in sent else UNSET,
        allowed_tools=data.allowed_tools if "allowed_tools" in sent else UNSET,
    )
    session.commit()
    return _read(state)
