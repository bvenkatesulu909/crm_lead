"""Request and response bodies of /api/v1/custom-agents (ADR 0034, AB3).

Input bodies accept exactly the fields below and nothing else: the organisation, the agent's key,
its version numbers and who made it are the server's to set, never the client's.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.custom_agents import rules


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomAgentDefinitionIn(_Input):
    # Lengths are checked by the service after cleaning (a clear message beats a bare 422).
    name: str = Field(max_length=400)
    purpose: str = Field(max_length=2_000)
    instruction: str = Field(max_length=20_000)
    read_sets: list[str] = Field(max_length=20)
    suggestion_kinds: list[str] = Field(max_length=20)


class CustomAgentDefinitionUpdate(CustomAgentDefinitionIn):
    # The agent's version counter as the editor last saw it (a lost update is refused).
    version: int = Field(ge=1)


class CustomAgentRecordIn(_Input):
    record_id: uuid.UUID


class CustomAgentVersionRead(BaseModel):
    version_no: int
    purpose: str
    instruction: str
    read_sets: list[str]
    suggestion_kinds: list[str]
    cleaned: list[str]
    created_by_user_id: uuid.UUID
    created_at: datetime


class CustomAgentRead(BaseModel):
    id: uuid.UUID
    # The agent's key in the AI agents registry (switch, budget, usage live there).
    agent_key: str
    name: str
    purpose: str
    # What kind of record the agent is run on: lead, account or deal.
    record_type: str
    read_sets: list[str]
    suggestion_kinds: list[str]
    # Only people who may define agents see the instruction.
    instruction: str | None
    current_version: int
    # The counter to send back when editing (`version` in the update body).
    version: int
    enabled: bool
    # Has the CURRENT version had a successful dry run? An agent cannot be switched on or run
    # before.
    tried: bool
    created_at: datetime
    updated_at: datetime


class CustomAgentPage(BaseModel):
    items: list[CustomAgentRead]
    max_agents: int = rules.MAX_AGENTS


class CustomAgentMenuItem(BaseModel):
    key: str
    description: str
    record_type: str | None = None


class CustomAgentMenusRead(BaseModel):
    """What an administrator can choose from, and the limits of a definition."""

    read_sets: list[CustomAgentMenuItem]
    suggestion_kinds: list[CustomAgentMenuItem]
    max_read_sets: int
    max_suggestion_kinds: int
    max_agents: int
    name_max: int
    purpose_max: int
    instruction_max: int


class CustomAgentTrialRead(BaseModel):
    """What the agent WOULD do on one record. Nothing was proposed or changed."""

    run_id: uuid.UUID
    version_no: int
    action: str
    reason: str
    # The suggestion in a sentence, or None when nothing would be proposed.
    would_propose: str | None
    sets_shown: list[str]


class CustomAgentRunRead(BaseModel):
    id: uuid.UUID
    version_no: int
    mode: str
    record_type: str
    record_id: uuid.UUID
    action: str
    outcome: str
    proposal_id: uuid.UUID | None
    proposal_link: str | None
    # Why the safety check refused the suggestion, if it did.
    blocked_message: str | None = None
    user_id: uuid.UUID
    created_at: datetime


class CustomAgentRunPage(BaseModel):
    items: list[CustomAgentRunRead]
