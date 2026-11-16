"""/api/v1/custom-agents - the no-code agent builder (ADR 0034, AB3).

Thin layer: permissions, then the service; the write endpoints commit once. Tenant administrators
define agents and try them; sales staff run them on a record they may read. Whether an agent is
switched on is the AI agents registry's business (`PATCH /api/v1/agents/{agent_key}`).
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.custom_agents import repository, rules, run, run_rules, service
from app.modules.custom_agents.llm import model_for
from app.modules.custom_agents.models import CustomAgentRun, CustomAgentVersion
from app.modules.custom_agents.schemas import (
    CustomAgentDefinitionIn,
    CustomAgentDefinitionUpdate,
    CustomAgentMenuItem,
    CustomAgentMenusRead,
    CustomAgentPage,
    CustomAgentRead,
    CustomAgentRecordIn,
    CustomAgentRunPage,
    CustomAgentRunRead,
    CustomAgentTrialRead,
    CustomAgentVersionRead,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/custom-agents", tags=["custom-agents"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.CUSTOM_AGENT_MANAGE, Permission.CUSTOM_AGENT_RUN)),
]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.CUSTOM_AGENT_MANAGE))]
Runner = Annotated[Principal, Depends(require_any_permission(Permission.CUSTOM_AGENT_RUN))]


def custom_agent_model(request: Request) -> ChatModel:
    """The model behind custom agents. Tests put a scripted one on the app."""
    override: ChatModel | None = getattr(request.app.state, "custom_agent_model", None)
    return override or model_for(request.app.state.settings)


Model = Annotated[ChatModel, Depends(custom_agent_model)]


def _now() -> datetime:
    return datetime.now(UTC)


def _agent_read(
    session: Session, principal: Principal, view: service.AgentView, settings: Settings
) -> CustomAgentRead:
    agent, current = view.agent, view.current
    state = agents_api.effective(
        session,
        agent.tenant_id,
        agent.agent_key,
        agents_api.Limits.from_settings(settings),
        _now(),
    )
    tried = repository.has_trial(session, agent.tenant_id, agent.id, current.version_no)
    manager = principal.has_permission(Permission.CUSTOM_AGENT_MANAGE)
    return CustomAgentRead(
        id=agent.id,
        agent_key=agent.agent_key,
        name=agent.name,
        purpose=current.purpose,
        record_type=rules.RECORD_TYPE_OF[current.read_sets[0]],
        read_sets=list(current.read_sets),
        suggestion_kinds=list(current.suggestion_kinds),
        instruction=current.instruction if manager else None,
        current_version=agent.current_version,
        version=agent.version,
        enabled=state.enabled,
        tried=tried,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _version_read(version: CustomAgentVersion) -> CustomAgentVersionRead:
    return CustomAgentVersionRead(
        version_no=version.version_no,
        purpose=version.purpose,
        instruction=version.instruction,
        read_sets=list(version.read_sets),
        suggestion_kinds=list(version.suggestion_kinds),
        cleaned=[str(code) for code in version.cleaned],
        created_by_user_id=version.created_by_user_id,
        created_at=version.created_at,
    )


def _run_read(record: CustomAgentRun, blocked_message: str | None = None) -> CustomAgentRunRead:
    return CustomAgentRunRead(
        id=record.id,
        version_no=record.version_no,
        mode=record.mode,
        record_type=record.record_type,
        record_id=record.record_id,
        action=record.action,
        outcome=record.outcome,
        proposal_id=record.proposal_id,
        proposal_link=f"/approvals/{record.proposal_id}" if record.proposal_id else None,
        blocked_message=blocked_message,
        user_id=record.user_id,
        created_at=record.created_at,
    )


@router.get(
    "/menus",
    summary="What an agent can read and suggest, and the limits of a definition",
    responses=problem_responses(401, 403),
)
def menus(principal: Reader) -> CustomAgentMenusRead:
    return CustomAgentMenusRead(
        read_sets=[
            CustomAgentMenuItem(key=key, description=text, record_type=rules.RECORD_TYPE_OF[key])
            for key, text in rules.READ_SETS.items()
        ],
        suggestion_kinds=[
            CustomAgentMenuItem(key=kind, description=_KIND_TEXT[kind])
            for kind in rules.SUGGESTION_KINDS
        ],
        max_read_sets=rules.MAX_READ_SETS,
        max_suggestion_kinds=rules.MAX_SUGGESTION_KINDS,
        max_agents=rules.MAX_AGENTS,
        name_max=rules.NAME_MAX,
        purpose_max=rules.PURPOSE_MAX,
        instruction_max=rules.INSTRUCTION_MAX,
    )


_KIND_TEXT = {
    "lead.set_status": "Suggest a new status for a lead (never 'converted').",
    "activity.create_task": "Suggest a follow-up task for the owner of the record.",
}


@router.get(
    "",
    summary="The custom agents of your organisation",
    description="Administrators see each agent's instruction; sales staff see only what they "
    "need to run it.",
    responses=problem_responses(401, 403),
)
def list_agents(principal: Reader, session: Db, request: Request) -> CustomAgentPage:
    settings: Settings = request.app.state.settings
    return CustomAgentPage(
        items=[
            _agent_read(session, principal, v, settings)
            for v in service.list_agents(session, principal)
        ]
    )


@router.post(
    "",
    status_code=201,
    summary="Define a new custom agent (it starts switched off)",
    description="Links, markup and hidden characters are removed from the typed text; words that "
    "try to change the AI's safety rules are refused. Read sets and suggestion kinds come only "
    "from the menus. An organisation can have at most 10 active agents.",
    responses=problem_responses(401, 403, 409, 422),
)
def create_agent(
    data: CustomAgentDefinitionIn, principal: Manager, session: Db, request: Request
) -> CustomAgentRead:
    view = service.create_agent(session, principal, **data.model_dump())
    session.commit()
    return _agent_read(session, principal, view, request.app.state.settings)


@router.get(
    "/{agent_id}",
    summary="One custom agent",
    responses=problem_responses(401, 403, 404),
)
def get_agent(
    agent_id: uuid.UUID, principal: Reader, session: Db, request: Request
) -> CustomAgentRead:
    view = service.get_agent(session, principal, agent_id)
    return _agent_read(session, principal, view, request.app.state.settings)


@router.put(
    "/{agent_id}",
    summary="Save a changed definition as the next version (older versions are kept)",
    description="Send `version` (the agent's counter as you last saw it) so two people cannot "
    "overwrite each other. A new version must have a dry run before it can be switched on or run.",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def update_agent(
    agent_id: uuid.UUID,
    data: CustomAgentDefinitionUpdate,
    principal: Manager,
    session: Db,
    request: Request,
) -> CustomAgentRead:
    view = service.update_agent(session, principal, agent_id, **data.model_dump())
    session.commit()
    return _agent_read(session, principal, view, request.app.state.settings)


@router.post(
    "/{agent_id}/archive",
    status_code=204,
    summary="Retire an agent: it can no longer be run or edited; its history stays",
    responses=problem_responses(401, 403, 404),
)
def archive_agent(agent_id: uuid.UUID, principal: Manager, session: Db) -> None:
    service.archive_agent(session, principal, agent_id)
    session.commit()


@router.get(
    "/{agent_id}/versions",
    summary="Every saved version of an agent, newest first",
    responses=problem_responses(401, 403, 404),
)
def list_versions(
    agent_id: uuid.UUID, principal: Manager, session: Db
) -> list[CustomAgentVersionRead]:
    return [_version_read(v) for v in service.list_versions(session, principal, agent_id)]


@router.post(
    "/{agent_id}/try",
    summary="Dry run for an administrator: show what the agent would suggest, nothing else",
    description="Uses the current version on one real record you may read. No proposal, no "
    "change; the model call counts against the agent's token budget. A valid answer counts as "
    "the dry run of this version, which is needed before the agent can be switched on. It works "
    "while the agent is still switched off.",
    responses=problem_responses(401, 403, 404, 422, 429, 503),
)
def try_agent(
    agent_id: uuid.UUID,
    data: CustomAgentRecordIn,
    principal: Manager,
    session: Db,
    request: Request,
    model: Model,
) -> CustomAgentTrialRead:
    settings: Settings = request.app.state.settings
    try:
        result = run.try_agent(
            session,
            principal,
            model,
            agent_id,
            data.record_id,
            limits=run.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except run.AnswerInvalidError:
        session.commit()  # the model was called: keep the tokens it used on the month's total
        raise
    session.commit()
    return CustomAgentTrialRead(
        run_id=result.run.id,
        version_no=result.run.version_no,
        action=result.suggestion.action,
        reason=result.suggestion.reason,
        would_propose=run_rules.summary(result.planned) if result.planned else None,
        sets_shown=result.sets_shown,
    )


@router.post(
    "/{agent_id}/runs",
    status_code=201,
    summary="Run an agent on one record; it suggests, a different person decides",
    description="The record must be one you may read, and the agent must be switched on and have "
    "had a dry run of its current version. The result may be a proposal in the approval queue "
    "(nothing changes until a different person approves it) or just a recorded run. Off, over "
    "budget or over a limit: 503 / 429 with nothing proposed.",
    responses=problem_responses(401, 403, 404, 409, 422, 429, 503),
)
def run_agent(
    agent_id: uuid.UUID,
    data: CustomAgentRecordIn,
    principal: Runner,
    session: Db,
    request: Request,
    model: Model,
) -> CustomAgentRunRead:
    settings: Settings = request.app.state.settings
    try:
        result = run.run_agent(
            session,
            principal,
            model,
            agent_id,
            data.record_id,
            limits=run.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except run.AnswerInvalidError:
        session.commit()  # keep the tokens the model used
        raise
    session.commit()
    return _run_read(result.run, result.blocked_message)


@router.get(
    "/{agent_id}/runs",
    summary="The newest runs and dry runs of an agent",
    responses=problem_responses(401, 403, 404),
)
def list_runs(
    agent_id: uuid.UUID,
    principal: Manager,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CustomAgentRunPage:
    return CustomAgentRunPage(
        items=[_run_read(r) for r in service.list_runs(session, principal, agent_id, limit=limit)]
    )
