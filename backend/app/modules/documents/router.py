"""Document endpoints: staff at /api/v1/documents, customers at /api/v1/portal/documents.

Thin layer: coarse permission (RBAC), then the service (record-level checks), commit once.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.storage import FileStore, get_file_store
from app.core.validation import Reason
from app.modules.documents import service
from app.modules.documents.schemas import (
    DocumentList,
    DocumentRead,
    PortalDocumentList,
    UploadRecordType,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/documents", tags=["documents"], responses=problem_responses(401, 403))
portal_router = APIRouter(
    prefix="/portal/documents", tags=["portal"], responses=problem_responses(401, 403)
)
Reader = Annotated[Principal, Depends(require_any_permission(Permission.DOCUMENT_READ))]
Writer = Annotated[Principal, Depends(require_any_permission(Permission.DOCUMENT_WRITE))]
Deleter = Annotated[Principal, Depends(require_any_permission(Permission.DOCUMENT_DELETE))]
Customer = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_DOCUMENT_READ))]
Db = Annotated[Session, Depends(get_db_session)]
Files = Annotated[FileStore, Depends(get_file_store)]
FILE: dict[int | str, dict[str, Any]] = {200: {"content": {"application/octet-stream": {}}}}


def _file_response(file_name: str, content_type: str, data: bytes) -> Response:
    # Always a download (never shown inline), and the browser must not guess another type.
    safe = file_name.replace('"', "_")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("", summary="Documents of an account or deal (newest version of each)")
def list_documents(
    principal: Reader,
    session: Db,
    record_type: UploadRecordType,
    record_id: uuid.UUID,
) -> DocumentList:
    return DocumentList(items=service.list_documents(session, principal, record_type, record_id))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (same file name on the same record = new version)",
    responses=problem_responses(404, 409, 413, 415, 422, 503),
)
async def upload_document(
    request: Request,
    principal: Writer,
    session: Db,
    files: Files,
    record_type: Annotated[UploadRecordType, Form()],
    record_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File(description="The file (max. size: see files_max_bytes).")],
    customer_visible: Annotated[bool, Form()] = False,
    description: Annotated[Reason | None, Form()] = None,
) -> DocumentRead:
    max_bytes: int = request.app.state.settings.files_max_bytes
    data = await file.read(max_bytes + 1)  # one byte more tells us it is too large
    result = service.upload(
        session,
        principal,
        files,
        record_type=record_type,
        record_id=record_id,
        file_name=file.filename,
        data=data,
        max_bytes=max_bytes,
        customer_visible=customer_visible,
        description=description or None,
    )
    session.commit()
    return result


@router.get(
    "/{document_id}/versions",
    summary="All versions of a document (newest first)",
    responses=problem_responses(404),
)
def document_versions(document_id: uuid.UUID, principal: Reader, session: Db) -> DocumentList:
    return DocumentList(items=service.versions(session, principal, document_id))


@router.get(
    "/{document_id}/download",
    summary="Download one version of a document",
    response_class=Response,
    responses={**problem_responses(404, 503), **FILE},
)
def download_document(
    document_id: uuid.UUID, principal: Reader, session: Db, files: Files
) -> Response:
    info, data = service.download(session, principal, files, document_id)
    return _file_response(info.file_name, info.content_type, data)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document with all its versions (managers)",
    responses=problem_responses(404),
)
def delete_document(
    document_id: uuid.UUID, principal: Deleter, session: Db, files: Files
) -> Response:
    keys = service.delete_document(session, principal, document_id)
    session.commit()
    service.remove_files(files, keys)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@portal_router.get("", summary="Documents shared with my company for one of my accounts")
def my_documents(
    principal: Customer, session: Db, account_id: Annotated[uuid.UUID, Query()]
) -> PortalDocumentList:
    return PortalDocumentList(items=service.portal_list(session, principal, account_id))


@portal_router.get(
    "/{document_id}/download",
    summary="Download a document shared with my company",
    response_class=Response,
    responses={**problem_responses(404, 503), **FILE},
)
def download_my_document(
    document_id: uuid.UUID, principal: Customer, session: Db, files: Files
) -> Response:
    info, data = service.portal_download(session, principal, files, document_id)
    return _file_response(info.file_name, info.content_type, data)
