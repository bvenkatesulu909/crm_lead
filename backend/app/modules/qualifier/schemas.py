"""Request and response bodies of /api/v1/qualifier (docs/qualifier.md).

The tenant, the version number and who saved never come from the client: the save body lists
the name, the steps and the version the person was looking at, nothing else is accepted.
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Wide bounds here; the service applies the exact rules after cleaning (and says which step).
Step = Annotated[str, Field(max_length=2000)]


class ProcedureSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=300)]
    steps: Annotated[list[Step], Field(min_length=1, max_length=40)]
    # The active version the person edited; omit it when there is none yet.
    replaces_version: Annotated[int | None, Field(ge=1)] = None


class ProcedureDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Annotated[int, Field(ge=1)]


class ProcedureRead(BaseModel):
    id: uuid.UUID
    version: int
    name: str
    steps: list[str]
    # Kinds of text taken out when it was saved (links, addresses, markup, hidden characters).
    cleaned: list[str]
    active: bool
    retired_at: datetime | None
    created_by_user_id: uuid.UUID
    created_at: datetime


class ProcedurePage(BaseModel):
    items: list[ProcedureRead]
    total: int
    limit: int
    offset: int
