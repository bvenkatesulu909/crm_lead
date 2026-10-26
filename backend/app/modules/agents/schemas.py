"""Request and response bodies of /api/v1/agents (ADR 0016).

The tenant, the key and everything the server decides never come from the client: the update
body lists the three settings an admin may change, nothing else is accepted.
"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.models import MAX_TOKENS

Tool = Annotated[str, Field(min_length=1, max_length=60)]


class AgentRead(BaseModel):
    key: str
    title: str
    description: str
    owner_role: str
    enabled: bool
    # What is in force: the organisation's own cap, or the default (budget_is_default).
    monthly_token_budget: int
    budget_is_default: bool
    allowed_tools: list[str]
    all_tools: list[str]
    month: date
    input_tokens: int
    output_tokens: int
    used_tokens: int
    calls: int
    percent_used: int
    # None until the organisation first changes the agent; send it back with the next change.
    version: int | None


class AgentPage(BaseModel):
    items: list[AgentRead]


class AgentUpdate(BaseModel):
    """Only the fields that are sent are changed. ``null`` for the budget or the tools means
    "back to the default"."""

    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    monthly_token_budget: int | None = Field(default=None, ge=1, le=MAX_TOKENS)
    allowed_tools: list[Tool] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _something_to_change(self) -> "AgentUpdate":
        changes = {"enabled", "monthly_token_budget", "allowed_tools"}
        if not changes & self.model_fields_set:
            raise ValueError("Say what to change: enabled, monthly_token_budget or allowed_tools.")
        if "enabled" in self.model_fields_set and self.enabled is None:
            raise ValueError("enabled must be true or false.")
        return self
