"""Branding endpoints (/api/v1/branding), tenant administrators only (ADR 0032). Thin: gate, call
the service, commit once."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.branding import rules, service
from app.modules.branding.schemas import BrandingRead, BrandingUpdate
from app.modules.identity.api import require_any_permission

Db = Annotated[Session, Depends(get_db_session)]
Admin = Annotated[Principal, Depends(require_any_permission(Permission.BRANDING_MANAGE))]

router = APIRouter(prefix="/branding", tags=["branding"], responses=problem_responses(401, 403))


@router.get("", summary="Your organisation's branding (tenant admins)")
def get_branding(principal: Admin, session: Db) -> BrandingRead:
    return service.get_branding(session, principal)


@router.put(
    "",
    summary="Change the colour and the texts (tenant admins)",
    responses=problem_responses(409, 422),
)
def update_branding(data: BrandingUpdate, principal: Admin, session: Db) -> BrandingRead:
    result = service.update_branding(session, principal, data)
    session.commit()
    return result


@router.put(
    "/logo",
    summary="Upload the logo (PNG or JPEG, at most 1 MB); it is stored as a clean PNG",
    responses=problem_responses(413, 422),
)
def upload_logo(
    principal: Admin,
    session: Db,
    file: Annotated[UploadFile, File(description="The logo picture.")],
) -> BrandingRead:
    # One byte more than the limit is read: an oversized file is refused without reading it all.
    data = file.file.read(rules.MAX_UPLOAD_BYTES + 1)
    result = service.set_logo(session, principal, data)
    session.commit()
    return result


@router.delete("/logo", summary="Remove the logo", responses=problem_responses(404))
def delete_logo(principal: Admin, session: Db) -> BrandingRead:
    result = service.remove_logo(session, principal)
    session.commit()
    return result


@router.get(
    "/logo",
    summary="The stored logo (PNG)",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, **problem_responses(404)},
)
def get_logo(principal: Admin, session: Db) -> Response:
    return Response(
        service.logo_png(session, principal),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
