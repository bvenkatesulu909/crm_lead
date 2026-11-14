"""Proposal decks of a quote (ADR 0032, PD3): ask for one, see its state, download it, and the
worker job that draws and stores it. Never commits; the router (or the worker) commits once.

A deck belongs to one quote and is stored as a document (purpose ``quote_deck`` for the PDF,
``quote_deck_pptx`` for the PowerPoint version, ADR 0032 Amendment A; each format has its own job,
state and newest file, so one never replaces the other). It is drawn by
the worker from the quote record and the organisation's branding at that moment, so it stays true
for ever like the quote PDF. The same quote with the same branding gives the same bytes, which are
stored once; a changed branding gives a new deck and the newest one is the one shown.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.outbox import Job, OutboxJob, PermanentJobError, enqueue, latest_job_status
from app.core.storage import FileStore
from app.modules.branding import api as branding_api
from app.modules.documents import api as documents_api
from app.modules.identity import api as identity_api
from app.modules.proposal_decks.data import DeckBrand, DeckData, DeckLine
from app.modules.proposal_decks.render import render_deck
from app.modules.proposal_decks.render_pptx import render_pptx
from app.modules.quotes import api as quotes_api

RECORD_TYPE = "quote"
ENTITY = "quote"

State = Literal["none", "queued", "ready", "failed", "not_available"]
Format = Literal["pdf", "pptx"]


@dataclass(frozen=True)
class _Kind:
    """What differs between the two formats: the worker job, the document purpose, the file type."""

    job: str
    purpose: str
    content_type: str
    suffix: str


KINDS: dict[Format, _Kind] = {
    "pdf": _Kind("quote.deck", "quote_deck", "application/pdf", "pdf"),
    "pptx": _Kind(
        "quote.deck_pptx",
        "quote_deck_pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
    ),
}
JOB = KINDS["pdf"].job
JOB_PPTX = KINDS["pptx"].job
JOBS = (JOB, JOB_PPTX)
PURPOSE = KINDS["pdf"].purpose


class DeckRateLimitedError(DomainError):
    status_code = 429
    code = "deck_rate_limited"

    def __init__(self) -> None:
        super().__init__("Too many proposal decks were asked for. Try again later.")


class DeckPendingError(ConflictError):
    code = "deck_pending"

    def __init__(self) -> None:
        super().__init__("A proposal deck for this quote is already being made.")


class DeckNotFoundError(NotFoundError):
    code = "deck_not_found"

    def __init__(self) -> None:
        super().__init__("There is no proposal deck for this quote yet.")


@dataclass(frozen=True)
class DeckState:
    state: State
    reason: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None
    refresh_failed: bool = False


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise ForbiddenError("Only members of an organisation can use proposal decks.")
    return principal.tenant_id, principal.user_id


def _job_state(
    session: Session, tenant_id: uuid.UUID, quote_id: uuid.UUID, fmt: Format
) -> str | None:
    return latest_job_status(session, tenant_id, KINDS[fmt].job, "quote_id", str(quote_id))


# --- people ---------------------------------------------------------------------------------


def request_deck(
    session: Session,
    principal: Principal,
    quote_id: uuid.UUID,
    settings: Settings,
    *,
    fmt: Format = "pdf",
    now: datetime | None = None,
) -> DeckState:
    """Queue the drawing of a deck in one format. Needs the right to change the quote (the quote
    module decides); refused for a quote not yet approved or one that was superseded, while one of
    the same format is already being made, and past the hourly limit (both formats count together)."""
    when = now or datetime.now(UTC)
    tenant_id, user_id = _ids(principal)
    source = quotes_api.deck_source(session, principal, quote_id, create=True)
    if _job_state(session, tenant_id, source.quote_id, fmt) in ("pending", "running"):
        raise DeckPendingError()
    recent = session.scalar(
        select(func.count())
        .select_from(OutboxJob)
        .where(
            OutboxJob.tenant_id == tenant_id,
            OutboxJob.kind.in_(JOBS),
            OutboxJob.payload["requested_by"].astext == str(user_id),
            OutboxJob.created_at > when - timedelta(hours=1),
        )
    )
    if (recent or 0) >= settings.proposal_decks_per_user_hour:
        raise DeckRateLimitedError()
    enqueue(
        session,
        tenant_id=tenant_id,
        kind=KINDS[fmt].job,
        payload={"quote_id": str(source.quote_id), "requested_by": str(user_id)},
    )
    record_audit(
        session,
        principal,
        action="deck.requested",
        entity_type=ENTITY,
        entity_id=source.quote_id,
        changes={"format": fmt},
    )
    session.flush()
    return DeckState("queued")


def deck_state(
    session: Session,
    principal: Principal,
    quote_id: uuid.UUID,
    *,
    customer: bool,
    fmt: Format = "pdf",
) -> DeckState:
    """Where the quote's deck stands. A customer sees only a finished deck (never the work in
    progress); staff also see "queued" and "failed"."""
    tenant_id, _ = _ids(principal)
    try:
        source = quotes_api.deck_source(session, principal, quote_id, create=False)
    except (quotes_api.QuoteNotReadyForDeckError, quotes_api.QuoteSupersededError) as why:
        return DeckState("not_available", reason=why.detail)
    doc = documents_api.latest_document(
        session, tenant_id, RECORD_TYPE, source.quote_id, KINDS[fmt].purpose
    )
    job = _job_state(session, tenant_id, source.quote_id, fmt)
    if customer:
        if doc is None or not doc.customer_visible:
            return DeckState("none")
        return DeckState("ready", None, doc.file_name, doc.size_bytes, doc.created_at)
    if job in ("pending", "running"):
        return DeckState("queued")
    if doc is not None:
        return DeckState(
            "ready",
            None,
            doc.file_name,
            doc.size_bytes,
            doc.created_at,
            refresh_failed=job == "dead",
        )
    return DeckState("failed" if job == "dead" else "none")


def deck_link(
    session: Session,
    principal: Principal,
    store: FileStore,
    quote_id: uuid.UUID,
    *,
    customer: bool,
    fmt: Format = "pdf",
) -> documents_api.DownloadLink:
    """A 60-second signed link to the newest deck of one format, under the quote's own read rules
    (ADR 0025)."""
    tenant_id, _ = _ids(principal)
    source = quotes_api.deck_source(session, principal, quote_id, create=False)
    doc = documents_api.latest_document(
        session, tenant_id, RECORD_TYPE, source.quote_id, KINDS[fmt].purpose
    )
    if doc is None or (customer and not doc.customer_visible):
        raise DeckNotFoundError()
    return documents_api.download_link(session, store, tenant_id, doc.id)


# --- the worker -----------------------------------------------------------------------------


def _deck_data(source: quotes_api.DeckSource, brand: DeckBrand) -> DeckData:
    return DeckData(
        number=source.number,
        title=source.title,
        customer=source.customer,
        contact=source.contact,
        issued=source.issued,
        valid_until=source.valid_until,
        currency=source.currency,
        lines=tuple(
            DeckLine(
                ln.position,
                ln.description,
                ln.quantity,
                ln.unit,
                ln.net_unit_price,
                ln.discount_percent,
                ln.tax_rate,
                ln.line_subtotal,
            )
            for ln in source.lines
        ),
        gross_total=source.gross_total,
        discount_total=source.discount_total,
        subtotal=source.subtotal,
        tax_total=source.tax_total,
        total=source.total,
        customer_note=source.customer_note,
        brand=brand,
    )


def run_job(session: Session, store: FileStore, job: Job) -> None:
    """Draw and store the deck of one quote in the format of the job's kind. Safe to run twice: the
    same bytes are stored once."""
    fmt: Format = "pptx" if job.kind == JOB_PPTX else "pdf"
    kind = KINDS[fmt]
    try:
        quote_id = uuid.UUID(str(job.payload["quote_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("the job has no valid quote id") from None
    requested_by = job.payload.get("requested_by")
    try:
        source = quotes_api.deck_source_for_job(session, job.tenant_id, quote_id)
    except (quotes_api.QuoteNotReadyForDeckError, quotes_api.QuoteSupersededError) as why:
        raise PermanentJobError(why.code) from None
    organisation = identity_api.tenant_name(session, job.tenant_id) or "Supplier"
    brand = branding_api.branding_for_deck(session, job.tenant_id)
    data = _deck_data(
        source,
        DeckBrand(
            organisation=organisation,
            color=brand.color,
            about_text=brand.about_text,
            terms_text=brand.terms_text,
            contact_line=brand.contact_line,
            footer_line=brand.footer_line,
            logo_png=brand.logo_png,
        ),
    )
    content = render_pptx(data) if fmt == "pptx" else render_deck(data)
    existing = documents_api.find_by_content(
        session, job.tenant_id, RECORD_TYPE, quote_id, kind.purpose, content
    )
    if existing is not None:
        return
    creator: uuid.UUID | None = None
    if isinstance(requested_by, str):
        try:
            creator = uuid.UUID(requested_by)
        except ValueError:
            creator = None  # a job without a valid requester is made by "the system"
    info = documents_api.store_generated_document(
        session,
        store,
        tenant_id=job.tenant_id,
        record_type=RECORD_TYPE,
        record_id=quote_id,
        purpose=kind.purpose,
        file_name=f"{source.number.replace(' rev ', '-rev')}-proposal.{kind.suffix}",
        content_type=kind.content_type,
        data=content,
        customer_visible=True,
        created_by_user_id=creator,
        unique_by_content=True,
    )
    robot = identity_api.automation_principal(session, job.tenant_id)
    record_audit(
        session,
        robot,
        action="deck.created",
        entity_type=ENTITY,
        entity_id=quote_id,
        changes={
            "document_id": info.id,
            "size_bytes": info.size_bytes,
            "branding_version": brand.version,
            "format": fmt,
        },
    )
    session.flush()
