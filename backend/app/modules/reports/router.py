"""Report endpoints at /api/v1/reports (staff). The builder routes come first, so "builder"
is never read as a report key."""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import get_principal
from app.modules.reports import service
from app.modules.reports.schemas import ReportCatalogue, ReportOut, TableOut

router = APIRouter(prefix="/reports", tags=["reports"], responses=problem_responses(401, 403))
Me = Annotated[Principal, Depends(get_principal)]
Db = Annotated[Session, Depends(get_db_session)]
Start = Annotated[date | None, Query()]
End = Annotated[date | None, Query()]
Owner = Annotated[uuid.UUID | None, Query(description="Sales rep (managers and admins).")]
Columns = Annotated[list[str], Query(max_length=30)]
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}}}


def _staff(principal: Principal) -> Principal:
    if principal.user_type != "staff":
        # Reports are part of the staff CRM; customers and platform operators have none.
        from app.core.errors import ForbiddenError

        raise ForbiddenError("Reports are only available to staff.")
    return principal


def _csv(data: bytes, name: str) -> Response:
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("", summary="Reports and record types available to you")
def catalogue(principal: Me) -> ReportCatalogue:
    return service.catalogue(_staff(principal))


@router.get(
    "/builder/{record_type}",
    summary="Report builder: records of one type with chosen columns (preview)",
    responses=problem_responses(404, 422),
)
def builder(
    record_type: str,
    principal: Me,
    session: Db,
    columns: Columns = [],  # noqa: B006 - FastAPI query list default
    start: Start = None,
    end: End = None,
    owner_id: Owner = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=service.PREVIEW_ROWS),
) -> TableOut:
    return service.run_builder(session, _staff(principal), record_type, columns=columns,
                               start=start, end=end, owner_id=owner_id, status=status,
                               limit=limit, export=False)  # fmt: skip


@router.get(
    "/builder/{record_type}/csv",
    summary="Report builder: download as CSV (audited)",
    response_class=Response,
    responses={**problem_responses(404, 422), **CSV},
)
def builder_csv(
    record_type: str,
    principal: Me,
    session: Db,
    columns: Columns = [],  # noqa: B006
    start: Start = None,
    end: End = None,
    owner_id: Owner = None,
    status: str | None = None,
) -> Response:
    table = service.run_builder(session, _staff(principal), record_type, columns=columns,
                                start=start, end=end, owner_id=owner_id, status=status,
                                limit=service.CSV_ROWS, export=True)  # fmt: skip
    session.commit()  # the audit entry
    return _csv(service.to_csv([table]), f"{record_type}-export")


@router.get("/{key}", summary="One standard report", responses=problem_responses(404, 422))
def report(
    key: str,
    principal: Me,
    session: Db,
    start: Start = None,
    end: End = None,
    owner_id: Owner = None,
) -> ReportOut:
    return service.run_report(
        session, _staff(principal), key, start=start, end=end, owner_id=owner_id
    )


@router.get(
    "/{key}/csv",
    summary="One standard report as CSV",
    response_class=Response,
    responses={**problem_responses(404, 422), **CSV},
)
def report_csv(
    key: str,
    principal: Me,
    session: Db,
    start: Start = None,
    end: End = None,
    owner_id: Owner = None,
) -> Response:
    out = service.run_report(
        session, _staff(principal), key, start=start, end=end, owner_id=owner_id
    )
    return _csv(service.to_csv(out.sections), f"{key}-{out.start}-{out.end}")
