"""/api/v1/leads/{lead_id}/calls - call recordings of one lead (ADR 0030, staff only).

Thin layer: the coarse permission, then the service (which also checks that the person may read the
lead - else 404). Write endpoints commit once; a refusal of the FILE (not audio, too large) commits
the row as ``failed`` before the error is returned."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.storage import FileStore, get_file_store
from app.modules.calls import service
from app.modules.calls.schemas import (
    CallDetail,
    CallPage,
    CallRead,
    ListenLink,
    UploadStart,
    UploadTicket,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/leads", tags=["calls"], responses=problem_responses(401, 403))
Db = Annotated[Session, Depends(get_db_session)]
Store = Annotated[FileStore, Depends(get_file_store)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.CALL_READ))]
Writer = Annotated[Principal, Depends(require_any_permission(Permission.CALL_WRITE))]


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post(
    "/{lead_id}/calls/uploads",
    status_code=status.HTTP_201_CREATED,
    summary="Start adding a call recording: checks, then a short-lived signed upload link",
    responses=problem_responses(404, 413, 422, 429, 503),
)
def start_upload(
    lead_id: uuid.UUID,
    body: UploadStart,
    request: Request,
    principal: Writer,
    session: Db,
    store: Store,
) -> UploadTicket:
    ticket = service.start_upload(session, principal, store, lead_id, body, _settings(request))
    session.commit()
    return ticket


@router.post(
    "/{lead_id}/calls/{call_id}/finish",
    summary="Finish an upload: check the file that arrived and queue it for processing",
    responses=problem_responses(404, 409, 410, 413, 422),
)
def finish_upload(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    request: Request,
    principal: Writer,
    session: Db,
    store: Store,
) -> CallRead:
    try:
        result = service.finish_upload(
            session, principal, store, lead_id, call_id, _settings(request)
        )
    except service.FILE_REFUSALS:
        session.commit()  # keep the row as "failed" with its reason
        raise
    session.commit()
    return result


@router.get(
    "/{lead_id}/calls",
    summary="The recordings of a lead, newest first",
    responses=problem_responses(404),
)
def list_calls(lead_id: uuid.UUID, principal: Reader, session: Db) -> CallPage:
    return service.list_calls(session, principal, lead_id)


@router.get(
    "/{lead_id}/calls/{call_id}",
    summary="One recording with its transcript",
    responses=problem_responses(404),
)
def get_call(lead_id: uuid.UUID, call_id: uuid.UUID, principal: Reader, session: Db) -> CallDetail:
    return service.get_call(session, principal, lead_id, call_id)


@router.get(
    "/{lead_id}/calls/{call_id}/listen",
    summary="A 60-second link to listen to the recording (the cleaned copy when there is one)",
    responses=problem_responses(404, 409, 410),
)
def listen(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    principal: Reader,
    session: Db,
    store: Store,
) -> ListenLink:
    link = service.listen_link(session, principal, store, lead_id, call_id)
    session.commit()  # the audit entry
    return link


@router.delete(
    "/{lead_id}/calls/{call_id}/audio",
    summary="Delete the audio of a recording (its transcript and consent record stay)",
    responses=problem_responses(404),
)
def delete_audio(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    principal: Writer,
    session: Db,
    store: Store,
) -> CallRead:
    result = service.delete_audio(session, principal, store, lead_id, call_id)
    session.commit()
    return result
