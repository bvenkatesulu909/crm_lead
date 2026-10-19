"""Dashboard endpoint (/api/v1/dashboard). Read-only."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.dashboard import service
from app.modules.dashboard.schemas import DashboardRead, View
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/dashboard", tags=["dashboard"], responses=problem_responses(401, 403))
Viewer = Annotated[
    Principal,
    Depends(
        require_any_permission(
            Permission.DASHBOARD_EXECUTIVE,
            Permission.DASHBOARD_SALES_ALL,
            Permission.DASHBOARD_SALES_OWN,
        )
    ),
]


@router.get(
    "",
    summary="Dashboard figures for your role",
    description="`view`: executive (tenant admins), manager (sales managers and admins) or "
    "representative (your own records). Default: the widest view you have. `start`/`end` "
    "(dates, default: the last 30 days) limit period figures such as leads created or orders "
    "confirmed; counts marked *now* are current. `owner_id` (manager/executive views) narrows "
    "everything to one sales rep. All figures respect your normal access rights.",
    responses=problem_responses(422),
)
def get_dashboard(
    principal: Viewer,
    session: Annotated[Session, Depends(get_db_session)],
    view: View | None = None,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    owner_id: uuid.UUID | None = None,
) -> DashboardRead:
    return service.build_dashboard(
        session, principal, view=view, start=start, end=end, owner_id=owner_id
    )
