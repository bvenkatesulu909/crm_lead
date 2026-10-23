"""Contract endpoints at /api/v1/contracts (staff only).

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.contracts import service
from app.modules.contracts.repository import ContractFilters
from app.modules.contracts.schemas import (
    ContractCreate,
    ContractEventRead,
    ContractPage,
    ContractRead,
    ContractStatus,
    ContractUpdate,
    NoteInput,
    RenewInput,
    Step,
    TerminateStep,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/contracts", tags=["contracts"], responses=problem_responses(401, 403))
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.CONTRACT_READ_ALL, Permission.CONTRACT_READ_OWN)),
]
Writer = Annotated[
    Principal,
    Depends(require_any_permission(Permission.CONTRACT_WRITE_ALL, Permission.CONTRACT_WRITE_OWN)),
]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.CONTRACT_MANAGE))]
Db = Annotated[Session, Depends(get_db_session)]
STEP = problem_responses(404, 409, 422)


@router.get("", summary="List contracts you may see (newest first)")
def list_contracts(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    contract_status: Annotated[list[ContractStatus] | None, Query(alias="status")] = None,
    account_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    ending_within_days: Annotated[
        int | None,
        Query(ge=0, le=365, description="Active contracts ending within this many days."),
    ] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> ContractPage:
    filters = ContractFilters(
        q=q,
        statuses=tuple(contract_status or ()),
        account_id=account_id,
        owner_id=owner_id,
        ending_within_days=ending_within_days,
        today=datetime.now(UTC).date(),
        limit=limit,
        offset=offset,
    )
    items, total = service.list_contracts(session, principal, filters)
    return ContractPage(
        items=service.summaries(session, principal.tenant_id or uuid.UUID(int=0), items),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft contract",
    responses=problem_responses(404, 422),
)
def create_contract(
    data: ContractCreate, principal: Writer, session: Db, response: Response
) -> ContractRead:
    contract = service.create_contract(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/contracts/{contract.id}"
    return service.to_read(session, contract)


@router.get("/{contract_id}", summary="Get one contract", responses=problem_responses(404))
def get_contract(contract_id: uuid.UUID, principal: Reader, session: Db) -> ContractRead:
    return service.to_read(session, service.get_contract(session, principal, contract_id))


@router.get(
    "/{contract_id}/history",
    summary="Status changes and notes (newest first)",
    responses=problem_responses(404),
)
def history(contract_id: uuid.UUID, principal: Reader, session: Db) -> list[ContractEventRead]:
    return service.history(session, principal, contract_id)


@router.patch(
    "/{contract_id}",
    summary="Change a draft, or the owner, notice, auto-renew and terms of an active contract",
    responses=STEP,
)
def update_contract(
    contract_id: uuid.UUID, data: ContractUpdate, principal: Writer, session: Db
) -> ContractRead:
    contract = service.update_contract(session, principal, contract_id, data)
    session.commit()
    return service.to_read(session, contract)


@router.post(
    "/{contract_id}/notes", summary="Add a note to the history", responses=problem_responses(404)
)
def add_note(
    contract_id: uuid.UUID, data: NoteInput, principal: Writer, session: Db
) -> ContractRead:
    contract = service.add_note(session, principal, contract_id, data.note)
    session.commit()
    return service.to_read(session, contract)


@router.post(
    "/{contract_id}/activate",
    summary="Activate a draft (managers); a renewal replaces the contract it renews",
    responses=STEP,
)
def activate(contract_id: uuid.UUID, data: Step, principal: Manager, session: Db) -> ContractRead:
    contract = service.activate(
        session, principal, contract_id, version=data.version, note=data.note
    )
    session.commit()
    return service.to_read(session, contract)


@router.post(
    "/{contract_id}/terminate",
    summary="End an active contract early, with a reason (managers)",
    responses=STEP,
)
def terminate(
    contract_id: uuid.UUID, data: TerminateStep, principal: Manager, session: Db
) -> ContractRead:
    contract = service.terminate(
        session, principal, contract_id, version=data.version, reason=data.reason
    )
    session.commit()
    return service.to_read(session, contract)


@router.post(
    "/{contract_id}/renew",
    status_code=status.HTTP_201_CREATED,
    summary="Create the renewal as a new draft (managers); activate it to complete the renewal",
    responses=STEP,
)
def renew(
    contract_id: uuid.UUID,
    data: RenewInput,
    principal: Manager,
    session: Db,
    response: Response,
) -> ContractRead:
    renewal = service.renew(session, principal, contract_id, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/contracts/{renewal.id}"
    return service.to_read(session, renewal)
