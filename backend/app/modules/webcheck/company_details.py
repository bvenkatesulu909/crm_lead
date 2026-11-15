"""Company details on a lead: ask, look up, suggest, apply (BP-02, ADR 0026 step EN3).

* **Ask** (``request_lookup``): the person may run web checks and read the lead (else the same
  404 as for a lead that does not exist); the feature is switched on for the organisation
  (registry entry ``company_details``, off by default) and on the platform (the web check's own
  switch); the host is worked out HERE from the lead (ADR 0019 Amendment B) - nobody sends one;
  the limits per person and per organisation hold. Then ONE job with ids and the host.
* **Look up** (``run_lookup``, the worker): ``lookup_company`` through the real fetcher (the demo
  sites only with the demo on), stored as insert-only evidence under source ``company_site`` with
  the suggestions in ``suggestions``; the person who asked is told (event ``webcheck.completed``).
  Safe to run twice; a temporary failure is retried, the last try stores the error.
* **Read** (``company_details``): the lead's current values next to the newest suggestions.
* **Apply** (``apply_suggestions``): the person names the FIELDS to keep; the VALUES come from the
  stored evidence, never from the request, and are saved through the leads module's normal update
  (write rules, version, checks, audit), plus a ``lead.enriched`` audit naming the evidence.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import DomainError, NotFoundError
from app.core.outbox import Job, PermanentJobError, enqueue
from app.core.webfetch import (
    FetchPolicy,
    HostLimiter,
    Resolver,
    Transport,
    real_transport,
    system_resolver,
)
from app.modules.agents import api as agents_api
from app.modules.leads import api as leads_api
from app.modules.webcheck import repository
from app.modules.webcheck.company_site import (
    DEMO_SUFFIX,
    CompanyHostRefused,
    check_host,
    company_host,
    lookup_company,
)
from app.modules.webcheck.fake import DemoCompanySites
from app.modules.webcheck.models import WebEvidence
from app.modules.webcheck.service import (
    COMPANY_SOURCE,
    MAX_ATTEMPTS,
    TRANSIENT_CODES,
    RecordNotFoundError,
    RequestedCheck,
    TemporaryFailure,
    WebCheckDisabledError,
    _announce,
    _person,
    _Request,
)

logger = logging.getLogger(__name__)

COMPANY_JOB = "webcheck.company_details"
AGENT_KEY = "company_details"
# Which suggestion fills which lead field.
FIELD_KEYS = {
    "company_website": "website",
    "company_industry": "industry",
    "company_size": "size",
}


class CompanyDetailsDisabledError(DomainError):
    status_code = 503
    code = "company_details_unavailable"

    def __init__(self) -> None:
        super().__init__("Company details are switched off for your organisation.")


class CompanyHostError(DomainError):
    """No company website can be looked up for this lead; the reason is ours and fixed."""

    status_code = 422

    def __init__(self, refused: CompanyHostRefused) -> None:
        self.code = f"company_host_{refused.code}"
        super().__init__(str(refused))


class CompanyDetailsLimitError(DomainError):
    status_code = 429
    code = "company_details_limit_reached"

    def __init__(self) -> None:
        super().__init__("Too many company look-ups in a short time. Try again later.")


class SuggestionNotFoundError(NotFoundError):
    code = "company_details_not_found"

    def __init__(self) -> None:
        super().__init__("These company details do not exist for this lead.")


class FieldNotSuggestedError(DomainError):
    status_code = 422
    code = "field_not_suggested"

    def __init__(self) -> None:
        super().__init__("Only fields with a suggestion can be saved.")


# --- asking -------------------------------------------------------------------------------------


def request_lookup(
    session: Session, principal: Principal, lead_id: uuid.UUID, *, settings: Settings
) -> RequestedCheck:
    if settings.webcheck_disabled:
        raise WebCheckDisabledError
    tenant_id, user_id = _person(principal, Permission.WEBCHECK_RUN)
    now = datetime.now(UTC)
    limits = agents_api.Limits.default()
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, limits, now)
    except agents_api.AgentUnavailableError:
        raise CompanyDetailsDisabledError() from None
    company = leads_api.lead_company(session, principal, lead_id)
    if company is None:
        raise RecordNotFoundError
    try:
        host = company_host(company.website, company.email, demo=settings.webcheck_demo)
    except CompanyHostRefused as refused:
        raise CompanyHostError(refused) from None
    if (
        repository.count_requests(
            session,
            tenant_id=tenant_id,
            kind=COMPANY_JOB,
            since=now - timedelta(hours=1),
            user_id=user_id,
        )
        >= settings.company_details_per_user_hour
        or repository.count_requests(
            session, tenant_id=tenant_id, kind=COMPANY_JOB, since=now - timedelta(days=1)
        )
        >= settings.company_details_per_tenant_day
    ):
        raise CompanyDetailsLimitError()
    agents_api.record_usage(
        session, tenant_id, AGENT_KEY, input_tokens=0, output_tokens=0, limits=limits, now=now
    )
    request_id = uuid.uuid4()
    enqueue(
        session,
        tenant_id=tenant_id,
        kind=COMPANY_JOB,
        payload={
            "request_id": str(request_id),
            "target_type": "lead",
            "target_id": str(lead_id),
            "host": host,
            "requested_by_user_id": str(user_id),
        },
    )
    record_audit(
        session,
        principal,
        action="webcheck.company_details_requested",
        entity_type="lead",
        entity_id=lead_id,
        changes={"host": host, "request_id": str(request_id)},
    )
    return RequestedCheck(request_id)


# --- looking up (the worker) --------------------------------------------------------------------


def _read(payload: Mapping[str, Any]) -> tuple[_Request, str]:
    try:
        request = _Request(
            request_id=uuid.UUID(str(payload["request_id"])),
            target_type="lead",
            target_id=uuid.UUID(str(payload["target_id"])),
            source_key=COMPANY_SOURCE,
            query=str(payload["host"])[:200],
            requested_by=uuid.UUID(str(payload["requested_by_user_id"])),
        )
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("payload of the company details job is not valid") from exc
    return request, request.query


def _store(session: Session, tenant_id: uuid.UUID, request: _Request, **fields: Any) -> WebEvidence:
    return repository.add_evidence(
        session,
        WebEvidence(
            tenant_id=tenant_id,
            request_id=request.request_id,
            target_type="lead",
            target_id=request.target_id,
            source_key=COMPANY_SOURCE,
            query=request.query,
            requested_by_user_id=request.requested_by,
            **fields,
        ),
    )


def run_lookup(
    session: Session,
    job: Job,
    *,
    settings: Settings,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
    limiter: HostLimiter | None = None,
    policy: FetchPolicy | None = None,
) -> None:
    request, raw_host = _read(job.payload)
    tenant_id = job.tenant_id
    bind_tenant(session, tenant_id)
    if repository.get_by_request(session, tenant_id, request.request_id) is not None:
        return
    if settings.webcheck_disabled:
        _store(session, tenant_id, request, verdict="error", error_code="source_unavailable")
        _announce(session, tenant_id, request, "error")
        return
    try:
        # Checked again here: the rules may have tightened since the person asked.
        host = check_host(raw_host, demo=settings.webcheck_demo)
    except CompanyHostRefused as refused:
        _store(session, tenant_id, request, verdict="error", error_code=f"host_{refused.code}")
        _announce(session, tenant_id, request, "error")
        return
    if resolver is None or transport is None:
        if settings.webcheck_demo and host.endswith(DEMO_SUFFIX):
            demo = DemoCompanySites()
            resolver, transport = resolver or demo.resolver, transport or demo.transport
        else:
            resolver, transport = resolver or system_resolver, transport or real_transport
    result = lookup_company(
        host,
        resolver=resolver,
        transport=transport,
        policy=policy or FetchPolicy(content_types=("text/html",)),
        limiter=limiter,
    )
    last_try = job.attempt >= min(MAX_ATTEMPTS, settings.worker_max_attempts)
    if result.website is None:
        code = result.refusal or "unreadable"
        if code in TRANSIENT_CODES and not last_try:
            raise TemporaryFailure(code)
        _store(session, tenant_id, request, verdict="error", error_code=code[:60])
        _announce(session, tenant_id, request, "error")
        return
    _store(
        session,
        tenant_id,
        request,
        verdict=result.verdict,
        http_status=200,
        final_url=(result.pages[0] if result.pages else result.website)[:2000],
        registered_name=result.name,
        excerpt=result.excerpt,
        cleaned=list(result.cleaned),
        suggestions={
            "website": result.website,
            "industry": result.industry,
            "size": result.size,
            "pages": list(result.pages),
        },
    )
    _announce(session, tenant_id, request, result.verdict)


# --- reading and applying -----------------------------------------------------------------------


@dataclass(frozen=True)
class CompanyDetails:
    current: leads_api.LeadCompany
    latest: WebEvidence | None


def company_details(session: Session, principal: Principal, lead_id: uuid.UUID) -> CompanyDetails:
    tenant_id, _ = _person(principal, Permission.WEBCHECK_READ)
    company = leads_api.lead_company(session, principal, lead_id)
    if company is None:
        raise RecordNotFoundError
    rows = repository.list_for_target(
        session, tenant_id, "lead", lead_id, 1, source_key=COMPANY_SOURCE
    )
    return CompanyDetails(current=company, latest=rows[0] if rows else None)


def apply_suggestions(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    *,
    evidence_id: uuid.UUID,
    fields: list[str],
    version: int,
) -> None:
    tenant_id, _ = _person(principal, Permission.WEBCHECK_RUN)
    if leads_api.lead_company(session, principal, lead_id) is None:
        raise RecordNotFoundError
    row = session.scalar(
        select(WebEvidence).where(
            WebEvidence.tenant_id == tenant_id,
            WebEvidence.id == evidence_id,
            WebEvidence.target_type == "lead",
            WebEvidence.target_id == lead_id,
            WebEvidence.source_key == COMPANY_SOURCE,
        )
    )
    if row is None or not isinstance(row.suggestions, dict):
        raise SuggestionNotFoundError()
    values: dict[str, str] = {}
    for name in fields:
        key = FIELD_KEYS.get(name)
        value = row.suggestions.get(key) if key else None
        if not isinstance(value, str) or not value:
            raise FieldNotSuggestedError()
        values[name] = value
    leads_api.apply_company_details(
        session, principal, lead_id, version=version, values=values, evidence_id=row.id
    )
