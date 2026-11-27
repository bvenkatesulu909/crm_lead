"""/api/v1/research-batches - research many accounts in one batch (ADR 0042, step BR4).

Thin layer: permission, then the service; the write endpoints commit once. Sales managers and tenant
administrators ask for an estimate, confirm it and start a batch; the worker does the research one
account at a time (see worker.py). Everything is read under the person's own rules.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.research_batches import repository, rules, service
from app.modules.research_batches.models import ResearchBatch
from app.modules.research_batches.schemas import (
    BatchDetailRead,
    BatchItemRead,
    BatchPage,
    BatchRead,
    BatchSelectionIn,
    BatchStartIn,
    BriefFiguresRead,
    EstimateRead,
    RetryEstimateIn,
    RetryStartIn,
)

router = APIRouter(prefix="/research-batches", tags=["research-batches"])
Db = Annotated[Session, Depends(get_db_session)]
Runner = Annotated[Principal, Depends(require_any_permission(Permission.RESEARCH_BATCH_RUN))]


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _request_of(body: BatchSelectionIn) -> service.BatchRequest:
    return service.BatchRequest(
        source=body.source,
        saved_filter_id=body.saved_filter_id,
        account_ids=tuple(body.account_ids),
        research_again=body.research_again,
    )


def _estimate_read(found: service.Estimate) -> EstimateRead:
    return EstimateRead(
        accounts=len(found.selection.accounts),
        not_available=found.selection.not_available,
        archived=found.selection.archived,
        reused=len(found.reused),
        calling_model=found.accounts_calling_model,
        upper_bound_tokens=found.upper_bound_tokens,
        typical_tokens=found.typical_tokens,
        estimated_cost_usd=found.estimated_cost_usd,
        cap_tokens=found.cap_tokens,
        monthly_tokens_left=found.monthly_tokens_left,
        daily_left=found.daily_left,
        worst_case_tokens_per_account=found.worst_case.total,
    )


def _batch_read(
    session: Session,
    principal: Principal,
    batch: ResearchBatch,
    counts: dict[str, int] | None = None,
) -> BatchRead:
    if counts is None:
        counts = rules.counts(
            item.status for item in repository.items(session, batch.tenant_id, batch.id)
        )
    return BatchRead(
        id=batch.id,
        status=batch.status,
        source=batch.source,
        saved_filter_id=batch.saved_filter_id,
        account_count=batch.account_count,
        not_available_count=batch.not_available_count,
        archived_count=batch.archived_count,
        estimated_upper_tokens=batch.estimated_upper_tokens,
        estimated_cost_usd=batch.estimated_cost_usd,
        token_cap=batch.token_cap,
        tokens_used=batch.tokens_used,
        research_again=batch.research_again,
        cancel_requested=batch.cancel_requested,
        created_by_user_id=batch.created_by_user_id,
        mine=batch.created_by_user_id == principal.user_id,
        version=batch.version,
        created_at=batch.created_at,
        finished_at=batch.finished_at,
        counts=counts,
    )


@router.post(
    "/estimate",
    summary="What a batch would research and cost (nothing is written, no model is called)",
    responses=problem_responses(403, 404, 422, 429, 503),
)
def estimate_batch(
    body: BatchSelectionIn, principal: Runner, session: Db, request: Request
) -> EstimateRead:
    return _estimate_read(
        service.estimate(session, principal, _request_of(body), _settings(request))
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Start a batch with the cost you confirmed",
    responses=problem_responses(403, 404, 409, 422, 429, 503),
)
def start_batch(body: BatchStartIn, principal: Runner, session: Db, request: Request) -> BatchRead:
    batch = service.start(
        session,
        principal,
        _request_of(body),
        _settings(request),
        confirmed_upper_bound=body.confirmed_upper_bound_tokens,
    )
    session.commit()
    return _batch_read(session, principal, batch)


@router.get("", summary="The organisation's batches, newest first")
def list_batches(
    principal: Runner,
    session: Db,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> BatchPage:
    batches, total = service.list_batches(session, principal, limit=limit, offset=offset)
    return BatchPage(
        items=[_batch_read(session, principal, b) for b in batches],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{batch_id}",
    summary="One batch with its accounts, their state and the figures of each brief",
    responses=problem_responses(403, 404),
)
def get_batch(batch_id: uuid.UUID, principal: Runner, session: Db) -> BatchDetailRead:
    batch, items = service.get_batch(session, principal, batch_id)
    views = service.describe_items(session, principal, items)
    base = _batch_read(session, principal, batch, rules.counts(i.status for i in items))
    return BatchDetailRead(
        **base.model_dump(),
        items=[
            BatchItemRead(
                position=v.item.position,
                account_id=v.item.account_id,
                account_name=v.account_name,
                status=v.item.status,
                failure_code=v.item.failure_code,
                brief_id=v.item.brief_id,
                input_tokens=v.item.input_tokens,
                output_tokens=v.item.output_tokens,
                brief=(
                    BriefFiguresRead(
                        brief_id=v.overview.brief_id,
                        created_at=v.overview.created_at,
                        sentences=v.overview.sentences,
                        dropped=v.overview.dropped,
                        gathered=v.overview.gathered,
                        tokens=v.overview.tokens,
                    )
                    if v.overview
                    else None
                ),
            )
            for v in views
        ],
    )


@router.post(
    "/{batch_id}/cancel",
    summary="Ask a running batch to stop (the account being researched finishes)",
    responses=problem_responses(403, 404, 409),
)
def cancel_batch(batch_id: uuid.UUID, principal: Runner, session: Db) -> BatchRead:
    batch = service.cancel_batch(session, principal, batch_id)
    session.commit()
    return _batch_read(session, principal, batch)


@router.post(
    "/{batch_id}/retry/estimate",
    summary="What it would cost to try the failed (or not run) accounts of an ended batch again",
    responses=problem_responses(403, 404, 409, 422, 429, 503),
)
def estimate_retry(
    batch_id: uuid.UUID, body: RetryEstimateIn, principal: Runner, session: Db, request: Request
) -> EstimateRead:
    selection = service.retry_request(session, principal, batch_id, body.which)
    return _estimate_read(service.estimate(session, principal, selection, _settings(request)))


@router.post(
    "/{batch_id}/retry",
    status_code=status.HTTP_201_CREATED,
    summary="Start a NEW batch with the failed (or not run) accounts of an ended batch",
    responses=problem_responses(403, 404, 409, 422, 429, 503),
)
def start_retry(
    batch_id: uuid.UUID, body: RetryStartIn, principal: Runner, session: Db, request: Request
) -> BatchRead:
    selection = service.retry_request(session, principal, batch_id, body.which)
    batch = service.start(
        session,
        principal,
        selection,
        _settings(request),
        confirmed_upper_bound=body.confirmed_upper_bound_tokens,
    )
    session.commit()
    return _batch_read(session, principal, batch)
