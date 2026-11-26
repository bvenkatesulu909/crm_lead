"""/api/v1/photo-enhancer - adjusted copies of property photos (ADR 0039, staff only).

Thin layer: the service checks the permissions, that the person may see the photo (else 404), the
organisation's switch, what was asked for and the limits. A write commits once; a file is removed
from the store only after the commit."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.storage import FileStore, get_file_store
from app.modules.identity.api import require_any_permission
from app.modules.photo_enhancer import rules, service
from app.modules.photo_enhancer.schemas import (
    CopyLink,
    EnhancementCreate,
    EnhancementPage,
    EnhancementRead,
)

router = APIRouter(
    prefix="/photo-enhancer", tags=["photo-enhancer"], responses=problem_responses(401, 403)
)
Db = Annotated[Session, Depends(get_db_session)]
Store = Annotated[FileStore, Depends(get_file_store)]
# The coarse gates; the service repeats the permission check and adds the photo's own rules.
Enhancer = Annotated[Principal, Depends(require_any_permission(Permission.PHOTO_ENHANCE))]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.DOCUMENT_READ))]


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post(
    "/previews",
    summary="A small JPEG showing what the adjustments would do (nothing is stored)",
    responses={
        200: {"content": {"image/jpeg": {}}},
        **problem_responses(404, 422, 429, 503),
    },
    response_class=Response,
)
def preview(
    body: EnhancementCreate,
    request: Request,
    principal: Enhancer,
    session: Db,
    store: Store,
) -> Response:
    jpeg = service.preview(
        session, principal, store, body.document_id, body.operations, _settings(request)
    )
    return Response(
        jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/enhancements",
    status_code=status.HTTP_201_CREATED,
    summary="Ask for an adjusted copy of a photo (made in the background)",
    responses=problem_responses(404, 422, 429, 503),
)
def create(
    body: EnhancementCreate,
    request: Request,
    principal: Enhancer,
    session: Db,
) -> EnhancementRead:
    row = service.request_enhancement(
        session, principal, body.document_id, body.operations, _settings(request)
    )
    result = EnhancementRead.model_validate(row)
    session.commit()
    return result


@router.get(
    "/enhancements",
    summary="The adjusted copies asked for on one photo, newest first",
    responses=problem_responses(404),
)
def list_for_photo(document_id: uuid.UUID, principal: Reader, session: Db) -> EnhancementPage:
    rows = service.list_copies(session, principal, document_id)
    return EnhancementPage(
        items=[EnhancementRead.model_validate(r) for r in rows], caption=rules.DECK_CAPTION
    )


@router.get(
    "/enhancements/{enhancement_id}/link",
    summary="A 60-second link to download a finished adjusted copy",
    responses=problem_responses(404),
)
def copy_link(enhancement_id: uuid.UUID, principal: Reader, session: Db, store: Store) -> CopyLink:
    link = service.copy_link(session, principal, store, enhancement_id)
    return CopyLink(url=link.url, file_name=link.file_name, expires_at=link.expires_at)


@router.delete(
    "/enhancements/{enhancement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an adjusted copy (never the original photo)",
    responses=problem_responses(404),
)
def delete(enhancement_id: uuid.UUID, principal: Enhancer, session: Db, store: Store) -> Response:
    key = service.delete_copy(session, principal, enhancement_id)
    session.commit()
    service.remove_file(store, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
