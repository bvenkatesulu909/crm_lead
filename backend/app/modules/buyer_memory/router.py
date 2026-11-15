"""/api/v1/leads/{lead_id}/memory - buyer memory of one lead (ADR 0028, staff only).

Thin layer: the coarse permission, then the service (which also checks that the person may read
the lead - else 404); every write endpoint commits once."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.buyer_memory import rules, service
from app.modules.buyer_memory.schemas import (
    CopyResult,
    MemoryConfirm,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryKeyRead,
    MemoryRead,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/leads", tags=["buyer-memory"], responses=problem_responses(401, 403))
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.BUYER_MEMORY_READ))]
Writer = Annotated[Principal, Depends(require_any_permission(Permission.BUYER_MEMORY_WRITE))]


def _keys(keys: list[rules.MemoryKey]) -> list[MemoryKeyRead]:
    return [MemoryKeyRead(key=k.key, label=k.label) for k in keys]


@router.get(
    "/{lead_id}/memory",
    summary="What we know about this buyer: facts, assumptions, gaps and the history",
    responses=problem_responses(404),
)
def read_memory(lead_id: uuid.UUID, principal: Reader, session: Db) -> MemoryRead:
    arranged = service.view(session, principal, lead_id)
    return MemoryRead(
        keys=_keys(list(rules.KEYS)),
        current=[MemoryItemRead.model_validate(r) for r in arranged.current],
        history=[MemoryItemRead.model_validate(r) for r in arranged.history],
        gaps=_keys(arranged.gaps),
    )


@router.post(
    "/{lead_id}/memory",
    status_code=status.HTTP_201_CREATED,
    summary="Record a fact (with its source and a quote) or an assumption (with its reason)",
    responses=problem_responses(404, 409, 422),
)
def add_memory(
    lead_id: uuid.UUID, body: MemoryItemCreate, principal: Writer, session: Db
) -> MemoryItemRead:
    item = service.add_item(session, principal, lead_id, body)
    session.commit()
    return MemoryItemRead.model_validate(item)


@router.post(
    "/{lead_id}/memory/{item_id}/confirm",
    status_code=status.HTTP_201_CREATED,
    summary="Confirm an assumption: adds a fact (the assumption stays in the history)",
    responses=problem_responses(404, 409, 422),
)
def confirm_memory(
    lead_id: uuid.UUID, item_id: uuid.UUID, body: MemoryConfirm, principal: Writer, session: Db
) -> MemoryItemRead:
    item = service.confirm_item(session, principal, lead_id, item_id, body)
    session.commit()
    return MemoryItemRead.model_validate(item)


@router.post(
    "/{lead_id}/memory/copy-from-lead",
    summary="Copy the lead form's budget, property type and area in as facts (never overwrites)",
    responses=problem_responses(404),
)
def copy_from_lead(lead_id: uuid.UUID, principal: Writer, session: Db) -> CopyResult:
    added = service.copy_from_lead(session, principal, lead_id)
    session.commit()
    return CopyResult(added=added)
