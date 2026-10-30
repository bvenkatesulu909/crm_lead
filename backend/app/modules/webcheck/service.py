"""The web check (ADR 0019): ask for a check, run it in the worker, keep the evidence.

Asking (``request_check``) is quick and does no network: permission, a record the person may
read, a source that is switched on, a query in the right shape, the limits - then one queued job
and an audit entry. Running (``run_check``) is the worker's: the hardened fetcher, the source's
parser, one insert-only evidence row. Services never commit; the caller does.
"""

import hashlib
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.events import publish
from app.core.outbox import Job, PermanentJobError, enqueue
from app.core.webfetch import (
    FetchPolicy,
    FetchRefused,
    HostLimiter,
    Resolver,
    Transport,
    fetch,
    real_transport,
    system_resolver,
)
from app.modules.accounts import api as accounts_api
from app.modules.agents import api as agents_api
from app.modules.leads import api as leads_api
from app.modules.webcheck import repository, sources
from app.modules.webcheck.fake import DemoRegistry
from app.modules.webcheck.models import TARGET_TYPES, WebEvidence
from app.modules.webcheck.rules import InvalidQueryError

logger = logging.getLogger(__name__)

CHECK_JOB = "webcheck.run"
# Its entry in the agent registry (ADR 0016): the organisation's switch and the monthly count.
AGENT_KEY = "web_check"
RETENTION = timedelta(days=365)  # the database enforces the same figure (migration 0045)
MAX_ATTEMPTS = 3
LIST_LIMIT = 50
# Failures that may pass: the site was slow, busy or unreachable. They are tried again; only the
# last try is stored as evidence.
TRANSIENT_CODES = frozenset({"timeout", "network_error", "robots_unavailable", "rate_limited"})
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class WebCheckDisabledError(DomainError):
    status_code = 503
    code = "webcheck_disabled"

    def __init__(self) -> None:
        super().__init__("The web check is switched off.")


class SourceUnavailableError(DomainError):
    status_code = 422
    code = "source_unavailable"

    def __init__(self) -> None:
        super().__init__("This source is not available.")


class QueryNotValidError(DomainError):
    status_code = 422
    code = "invalid_query"


class InvalidTargetError(DomainError):
    status_code = 422
    code = "invalid_target"

    def __init__(self) -> None:
        super().__init__("A check can be made for a lead or an account.")


class RecordNotFoundError(NotFoundError):
    code = "record_not_found"

    def __init__(self) -> None:
        super().__init__("Record not found.")


class CheckLimitError(DomainError):
    status_code = 429
    code = "webcheck_limit_reached"

    def __init__(self) -> None:
        super().__init__("Too many web checks were asked for. Try again later.")


class TemporaryFailure(Exception):  # noqa: N818 - read as a condition, like the outbox's own
    """The site did not answer well this time; the job is tried again later."""


@dataclass(frozen=True)
class RequestedCheck:
    request_id: uuid.UUID


# --- who may, and for what ----------------------------------------------------------------------


def _person(principal: Principal, permission: Permission) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        not principal.has_permission(permission)
        or principal.user_id is None
        or principal.tenant_id is None
    ):
        raise ForbiddenError("You may not use the web check.")
    return principal.tenant_id, principal.user_id


def _check_target(
    session: Session, principal: Principal, target_type: str, target_id: uuid.UUID
) -> None:
    """The record must exist and be readable by this person: otherwise the answer is the same
    "not found" as for a record that does not exist (no hint that it is somebody else's)."""
    if target_type not in TARGET_TYPES:
        raise InvalidTargetError
    readable = (
        leads_api.is_readable_lead(session, principal, target_id)
        if target_type == "lead"
        else accounts_api.is_readable_account(session, principal, target_id)
    )
    if not readable:
        raise RecordNotFoundError


def _enabled(settings: Settings) -> dict[str, sources.Source]:
    configured = [key.strip() for key in settings.webcheck_sources.split(",") if key.strip()]
    try:
        return sources.enabled_sources(configured=configured, demo=settings.webcheck_demo)
    except ValueError:
        logger.warning("web check: CRM_WEBCHECK_SOURCES names a source that does not exist")
        return {}


def offered_sources(settings: Settings) -> list[sources.Source]:
    """The sources a person can choose from: those switched on, RERA sources first, then by key.
    Nothing at all when the platform switch is on."""
    if settings.webcheck_disabled:
        return []
    # RERA sources first: the form starts with the check people ask for most.
    return sorted(
        _enabled(settings).values(), key=lambda source: (source.kind != "rera", source.key)
    )


# --- asking -------------------------------------------------------------------------------------


def request_check(
    session: Session,
    principal: Principal,
    *,
    target_type: str,
    target_id: uuid.UUID,
    source_key: str,
    query: str,
    settings: Settings,
) -> RequestedCheck:
    if settings.webcheck_disabled:
        raise WebCheckDisabledError
    tenant_id, user_id = _person(principal, Permission.WEBCHECK_RUN)
    now = datetime.now(UTC)
    limits = agents_api.Limits.default()  # no AI platform switch: this feature calls no model
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, limits, now)
    except agents_api.AgentUnavailableError:
        raise WebCheckDisabledError from None  # the organisation switched the web check off
    _check_target(session, principal, target_type, target_id)
    source = _enabled(settings).get(source_key)
    if source is None:
        raise SourceUnavailableError
    try:
        clean_query = source.check_query(query)
    except InvalidQueryError as exc:
        raise QueryNotValidError(str(exc)) from None

    if (
        repository.count_requests(
            session,
            tenant_id=tenant_id,
            kind=CHECK_JOB,
            since=now - timedelta(hours=1),
            user_id=user_id,
        )
        >= settings.webcheck_per_user_hour
        or repository.count_requests(
            session, tenant_id=tenant_id, kind=CHECK_JOB, since=now - timedelta(days=1)
        )
        >= settings.webcheck_per_tenant_day
    ):
        raise CheckLimitError

    # Counted as one check of the month on the registry page (a request, not a result).
    agents_api.record_usage(
        session, tenant_id, AGENT_KEY, input_tokens=0, output_tokens=0, limits=limits, now=now
    )
    request_id = uuid.uuid4()
    # Ids and keys only (ADR 0005): no page, no person's data.
    enqueue(
        session,
        tenant_id=tenant_id,
        kind=CHECK_JOB,
        payload={
            "request_id": str(request_id),
            "target_type": target_type,
            "target_id": str(target_id),
            "source_key": source.key,
            "query": clean_query,
            "requested_by_user_id": str(user_id),
        },
    )
    record_audit(
        session,
        principal,
        action="webcheck.requested",
        entity_type="web_check",
        entity_id=request_id,
        changes={
            "target_type": target_type,
            "target_id": str(target_id),
            "source_key": source.key,
            "query": clean_query,
        },
    )
    return RequestedCheck(request_id)


# --- running (the worker) -----------------------------------------------------------------------


@dataclass(frozen=True)
class _Request:
    request_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    source_key: str
    query: str
    requested_by: uuid.UUID


def _read_payload(payload: Mapping[str, Any]) -> _Request:
    try:
        request = _Request(
            request_id=uuid.UUID(str(payload["request_id"])),
            target_type=str(payload["target_type"]),
            target_id=uuid.UUID(str(payload["target_id"])),
            source_key=str(payload["source_key"]),
            query=str(payload["query"]),
            requested_by=uuid.UUID(str(payload["requested_by_user_id"])),
        )
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("payload of the web check job is not valid") from exc
    if request.target_type not in TARGET_TYPES:
        raise PermanentJobError("payload of the web check job is not valid")
    return request


def _announce(session: Session, tenant_id: uuid.UUID, request: _Request, verdict: str) -> None:
    """Tell the person who asked (ADR 0006). Ids and the verdict code only: no text of a page."""
    publish(
        session,
        tenant_id,
        "webcheck.completed",
        {
            "target_type": request.target_type,
            "target_id": str(request.target_id),
            "verdict": verdict,
            "requested_by_user_id": str(request.requested_by),
        },
    )


def _store_error(session: Session, tenant_id: uuid.UUID, request: _Request, code: str) -> None:
    repository.add_evidence(
        session,
        WebEvidence(
            tenant_id=tenant_id,
            request_id=request.request_id,
            target_type=request.target_type,
            target_id=request.target_id,
            source_key=request.source_key,
            query=request.query,
            requested_by_user_id=request.requested_by,
            verdict="error",
            error_code=code,
            excerpt="",
            cleaned=[],
        ),
    )
    _announce(session, tenant_id, request, "error")


def run_check(
    session: Session,
    job: Job,
    *,
    settings: Settings,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
    limiter: HostLimiter | None = None,
    policy: FetchPolicy | None = None,
) -> None:
    """Run one queued check. Safe to run twice: a request with evidence is not run again.

    ``resolver`` and ``transport`` default to the real network for a real source and to the
    in-process demo registry for a demo source."""
    request = _read_payload(job.payload)
    tenant_id = job.tenant_id
    bind_tenant(session, tenant_id)
    if repository.get_by_request(session, tenant_id, request.request_id) is not None:
        return
    source = _enabled(settings).get(request.source_key)
    if settings.webcheck_disabled or source is None:
        _store_error(session, tenant_id, request, "source_unavailable")
        return
    try:
        query = source.check_query(request.query)
    except InvalidQueryError:
        _store_error(session, tenant_id, request, "invalid_query")
        return

    if resolver is None or transport is None:
        if source.demo:
            demo = DemoRegistry()
            resolver, transport = resolver or demo.resolver, transport or demo.transport
        else:
            resolver, transport = resolver or system_resolver, transport or real_transport
    last_try = job.attempt >= min(MAX_ATTEMPTS, settings.worker_max_attempts)
    try:
        result = fetch(
            source.url_for(query),
            host=source.host,
            resolver=resolver,
            transport=transport,
            policy=policy or FetchPolicy(),
            limiter=limiter,
        )
    except FetchRefused as refused:
        if refused.code in TRANSIENT_CODES and not last_try:
            raise TemporaryFailure(refused.code) from None
        _store_error(session, tenant_id, request, refused.code)
        return
    if result.status in TRANSIENT_STATUSES and not last_try:
        raise TemporaryFailure(f"status {result.status}")

    record = source.parse(result, query)
    repository.add_evidence(
        session,
        WebEvidence(
            tenant_id=tenant_id,
            request_id=request.request_id,
            target_type=request.target_type,
            target_id=request.target_id,
            source_key=source.key,
            query=query,
            requested_by_user_id=request.requested_by,
            verdict=record.verdict,
            http_status=result.status,
            final_url=result.final_url[:2000],
            body_sha256=hashlib.sha256(result.body).hexdigest(),
            registered_name=record.registered_name,
            status=record.status,
            valid_until=record.valid_until,
            excerpt=record.excerpt,
            cleaned=list(record.cleaned),
        ),
    )
    _announce(session, tenant_id, request, record.verdict)


# --- reading and retention ----------------------------------------------------------------------


def list_evidence(
    session: Session, principal: Principal, target_type: str, target_id: uuid.UUID
) -> list[WebEvidence]:
    """The evidence about one lead or account, newest first, for someone who may read it."""
    tenant_id, _ = _person(principal, Permission.WEBCHECK_READ)
    _check_target(session, principal, target_type, target_id)
    return repository.list_for_target(session, tenant_id, target_type, target_id, LIST_LIMIT)


def delete_expired(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    """Delete evidence older than the retention (the worker, once a minute, per organisation)."""
    return repository.delete_older_than(session, tenant_id, now - RETENTION)
