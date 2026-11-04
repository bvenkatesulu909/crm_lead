"""/api/v1/lead-agent - ask the optional lead agent to look at one lead (ADR 0022, step LA4).

Thin layer: permission, then the service; it commits once. The agent only suggests: any change
waits in the approval queue for a different person.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.identity.api import require_any_permission
from app.modules.lead_agent import service
from app.modules.lead_agent.llm import model_for
from app.modules.lead_agent.schemas import RunCreate, RunRead

router = APIRouter(prefix="/lead-agent", tags=["lead-agent"])
Db = Annotated[Session, Depends(get_db_session)]
# The same people who may run the Qualifier may ask the lead agent (ADR 0022).
Runner = Annotated[Principal, Depends(require_any_permission(Permission.QUALIFIER_RUN))]


def lead_agent_model(request: Request) -> ChatModel:
    """The model behind the lead agent. Tests put a scripted one on the app."""
    override: ChatModel | None = getattr(request.app.state, "lead_agent_model", None)
    return override or model_for(request.app.state.settings)


Model = Annotated[ChatModel, Depends(lead_agent_model)]


@router.post(
    "/runs",
    status_code=201,
    summary="Ask the lead agent to look at one lead; it suggests, a different person decides",
    description="Needs a lead you may read and the agent switched on by an administrator. The "
    "result may be a proposal in the approval queue (nothing changes until a different person "
    "approves it) or no suggestion. Off, over budget or over a limit: 503 / 429 with nothing "
    "proposed.",
    responses=problem_responses(401, 403, 404, 422, 429, 503),
)
def create_run(
    data: RunCreate, principal: Runner, session: Db, request: Request, model: Model
) -> RunRead:
    settings: Settings = request.app.state.settings
    try:
        result = service.run_lead_agent(
            session,
            principal,
            model,
            data.lead_id,
            limits=service.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except service.SuggestionInvalidError:
        session.commit()  # the model was called: keep the tokens it used on the month's total
        raise
    session.commit()
    proposal = result.proposal
    return RunRead(
        outcome=result.outcome,
        proposal_id=proposal.id if proposal else None,
        proposal_link=f"/approvals/{proposal.id}" if proposal else None,
        blocked_message=result.blocked_message,
    )
