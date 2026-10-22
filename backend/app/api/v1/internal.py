"""Internal, token-protected operations endpoints (R6). Never public by accident."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.observability.metrics import metrics_payload, refresh_operational_gauges

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/metrics", include_in_schema=False)
def get_metrics(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    settings = request.app.state.settings
    if not settings.metrics_enabled or settings.metrics_token is None:
        raise HTTPException(status_code=404)
    expected = "Bearer " + settings.metrics_token.get_secret_value()
    if not secrets.compare_digest(authorization or "", expected):
        raise HTTPException(status_code=401, detail="Metrics token required.")
    refresh_operational_gauges(request.app.state.db_engine)
    body, content_type = metrics_payload()
    return Response(content=body, media_type=content_type)
