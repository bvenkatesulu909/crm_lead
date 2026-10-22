"""Health check endpoints.

- ``/health``        liveness:  is the API process up? (never touches the database)
- ``/health/ready``  readiness: can the API serve real requests, i.e. is the database reachable?

Both are deliberately public (no login) so Docker and monitoring tools can call them, and
therefore return nothing sensitive - in particular, no database error details.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.config import Settings
from app.core.db import check_database, check_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


@router.get("/health", summary="API health check")
def get_health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


class ReadinessResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    vector: Literal["ok"]


@router.get(
    "/health/ready",
    summary="API readiness check (includes database)",
    responses={503: {"description": "Database unavailable"}},
)
def get_readiness(request: Request) -> ReadinessResponse:
    engine: Engine = request.app.state.db_engine
    try:
        check_database(engine)
        check_vector_store(engine)
    except (SQLAlchemyError, RuntimeError) as exc:
        # The exception type is enough to diagnose; the message could include host names.
        logger.warning("database readiness check failed", extra={"error": type(exc).__name__})
        raise HTTPException(status_code=503, detail="Database unavailable.") from exc
    return ReadinessResponse(status="ok", database="ok", vector="ok")
