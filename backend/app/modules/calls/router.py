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
from app.modules.calls import clips, service
from app.modules.calls.schemas import (
    CallDetail,
    CallPage,
    CallRead,
    ClipCreate,
    ClipEdit,
    ClipPage,
    ClipRead,
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


# --- highlight clips (ADR 0033) ---------------------------------------------------------------


@router.post(
    "/{lead_id}/calls/{call_id}/clips",
    status_code=status.HTTP_201_CREATED,
    summary="Make a highlight clip of a recording (3-120 seconds, cut in the background)",
    responses=problem_responses(404, 409, 410, 422, 429),
)
def create_clip(
    lead_id: uuid.UUID, call_id: uuid.UUID, body: ClipCreate, principal: Writer, session: Db
) -> ClipRead:
    clip = clips.create_clip(session, principal, lead_id, call_id, body)
    session.commit()
    return clip


@router.get(
    "/{lead_id}/calls/{call_id}/clips",
    summary="The clips of a recording, in the order they appear in the call",
    responses=problem_responses(404),
)
def list_clips(lead_id: uuid.UUID, call_id: uuid.UUID, principal: Reader, session: Db) -> ClipPage:
    return clips.list_clips(session, principal, lead_id, call_id)


@router.get(
    "/{lead_id}/calls/{call_id}/clips/{clip_id}/listen",
    summary="A 60-second link to listen to a clip",
    responses=problem_responses(404, 409, 410),
)
def listen_clip(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    clip_id: uuid.UUID,
    principal: Reader,
    session: Db,
    store: Store,
) -> ListenLink:
    link = clips.listen_clip(session, principal, store, lead_id, call_id, clip_id)
    session.commit()  # the audit entry
    return link


@router.patch(
    "/{lead_id}/calls/{call_id}/clips/{clip_id}",
    summary="Change the title and/or the note of a clip (its maker or a manager)",
    responses=problem_responses(403, 404, 422),
)
def edit_clip(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    clip_id: uuid.UUID,
    body: ClipEdit,
    principal: Writer,
    session: Db,
) -> ClipRead:
    clip = clips.edit_clip(session, principal, lead_id, call_id, clip_id, body)
    session.commit()
    return clip


@router.delete(
    "/{lead_id}/calls/{call_id}/clips/{clip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a clip and its audio (its maker or a manager)",
    responses=problem_responses(403, 404),
)
def delete_clip(
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    clip_id: uuid.UUID,
    principal: Writer,
    session: Db,
    store: Store,
) -> None:
    clips.delete_clip(session, principal, store, lead_id, call_id, clip_id)
    session.commit()
