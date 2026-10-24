"""Public interface of the quotes module. Other modules (and the worker) import only from here."""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError
from app.core.mail import Mailer
from app.core.outbox import DeadJobHandler, Job, JobHandler, PermanentJobError
from app.core.records import RecordFacts
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.core.storage import FileStore
from app.modules.quotes import repository, service
from app.modules.quotes.metrics import quote_table
from app.modules.quotes.models import QUOTE_STATUSES, Quote
from app.modules.quotes.policies import readable_quotes
from app.modules.quotes.repository import QuoteFilters
from app.modules.quotes.schemas import PortalQuoteRead, PortalQuoteSummary

__all__ = [
    "quote_table",
    "EXPORT",
    "export_table",
    "quote_facts",
    "expiring_quote_ids",
    "quote_people",
    "quote_brief",
    "quote_account_id",
    "customer_quotes",
    "customer_quote",
    "EMAIL_JOB",
    "PDF_JOB",
    "email_failed_handler",
    "email_job_handler",
    "pdf_job_handler",
]

PDF_JOB = service.PDF_JOB
EMAIL_JOB = service.EMAIL_JOB


def _uuid(job: Job, key: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(job.payload[key]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError(f"payload without a valid {key}") from exc


def pdf_job_handler(store: FileStore) -> JobHandler:
    """Worker handler for "quote.pdf": stores the PDF of a sent quote (safe to run twice)."""

    def handle(session: Session, job: Job) -> None:
        try:
            quote_id = uuid.UUID(str(job.payload["quote_id"]))
        except (KeyError, ValueError) as exc:
            raise PermanentJobError("payload without a valid quote_id") from exc
        service.run_pdf_job(session, store, job.tenant_id, quote_id)

    return handle


def email_job_handler(store: FileStore, mailer: Mailer, web_app_url: str) -> JobHandler:
    """Worker handler for "quote.email": e-mails the quote with its PDF to the contact."""

    def handle(session: Session, job: Job) -> None:
        service.run_email_job(
            session,
            store,
            mailer,
            tenant_id=job.tenant_id,
            quote_id=_uuid(job, "quote_id"),
            event_id=_uuid(job, "event_id"),
            web_app_url=web_app_url,
        )

    return handle


def email_failed_handler() -> DeadJobHandler:
    """Notes in the quote history that the e-mail could not be sent."""

    def handle(session: Session, job: Job, error: str) -> None:
        service.email_failed(session, job.tenant_id, _uuid(job, "quote_id"), error)

    return handle


def quote_brief(
    session: Session, principal: Principal, quote_id: uuid.UUID
) -> tuple[str, uuid.UUID | None, uuid.UUID | None] | None:
    """("QT-0007: title", owner, creator) for a quote this principal may see, else None."""
    quote = repository.get_readable(session, principal, quote_id)
    if quote is None:
        return None
    return f"{service.number_label(quote)}: {quote.title}", quote.owner_id, quote.created_by_user_id


def quote_account_id(
    session: Session, principal: Principal, quote_id: uuid.UUID
) -> tuple[bool, uuid.UUID | None]:
    """(visible?, account of the quote). Quotes the user may not see give (False, None)."""
    quote = repository.get_readable(session, principal, quote_id)
    return (False, None) if quote is None else (True, quote.account_id)


def quote_people(session: Session, tenant_id: uuid.UUID, quote_id: uuid.UUID) -> set[uuid.UUID]:
    """Owner and creator of a quote, for notifications. The caller still checks for each person
    whether they may see the quote (quote_brief)."""
    quote = repository.get_in_tenant(session, tenant_id, quote_id)
    if quote is None:
        return set()
    return {p for p in (quote.owner_id, quote.created_by_user_id) if p is not None}


def quote_facts(session: Session, principal: Principal, quote_id: uuid.UUID) -> RecordFacts | None:
    quote = repository.get_readable(session, principal, quote_id)
    if quote is None:
        return None
    return RecordFacts(
        record_type="quote",
        record_id=quote.id,
        label=f"{service.number_label(quote)}: {quote.title}",
        link=f"/quotes/{quote.id}",
        owner_id=quote.owner_id,
        account_id=quote.account_id,
        lead_id=None,
        values={
            "status": quote.status,
            "total": quote.total,
            "max_discount_percent": quote.max_discount_percent,
            "currency": quote.currency,
        },
    )


def expiring_quote_ids(
    session: Session, tenant_id: uuid.UUID, today: date, within_days: int
) -> list[uuid.UUID]:
    """Sent quotes whose validity ends within the next ``within_days`` days (schedules)."""
    return list(
        session.scalars(
            select(Quote.id).where(
                Quote.tenant_id == tenant_id,
                Quote.status == "sent",
                Quote.valid_until >= today,
                Quote.valid_until <= today + timedelta(days=within_days),
            )
        )
    )


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("number", "Quote no.", "number"),
        Column("revision", "Revision", "number"),
        Column("title", "Title", "text"),
        Column("account_id", "Account", "account"),
        Column("status", "Status", "text"),
        Column("total", "Total", "money"),
        Column("currency", "Currency", "text"),
        Column("max_discount_percent", "Largest discount %", "number"),
        Column("valid_until", "Valid until", "date"),
        Column("sent_at", "Sent", "datetime"),
        Column("owner_id", "Owner", "user"),
    ),
    statuses=QUOTE_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Quote,
        columns={key: getattr(Quote, key) for key in allowed},
        wanted=wanted,
        condition=readable_quotes(principal),
        created=Quote.created_at,
        owner=Quote.owner_id,
        status=Quote.status,
        filters=filters,
    )


# --- customer portal (used by the AI assistant) ---------------------------------------------


def customer_quotes(
    session: Session, principal: Principal, *, limit: int = 20
) -> list[PortalQuoteSummary]:
    """The customer's quotes, through the same portal policy used by /portal/quotes."""
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_QUOTE_READ
    ):
        raise ForbiddenError("Only customers can list their quotes.")
    items, _ = service.list_quotes(session, principal, QuoteFilters(limit=min(limit, 50)))
    return [PortalQuoteSummary.model_validate(service.summary_values(x)) for x in items]


def customer_quote(session: Session, principal: Principal, quote_id: uuid.UUID) -> PortalQuoteRead:
    """One of the customer's quotes; another account's quote is a 404."""
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_QUOTE_READ
    ):
        raise ForbiddenError("Only customers can read their quotes.")
    return service.to_portal(session, service.get_quote(session, principal, quote_id))


# --- staff assistant (read-only, record-policy enforced) -------------------------------------


def search_quotes(
    session: Session, principal: Principal, *, limit: int = 10
) -> list[dict[str, Any]]:
    if not (
        principal.has_permission(Permission.QUOTE_READ_ALL)
        or principal.has_permission(Permission.QUOTE_READ_OWN)
    ):
        raise ForbiddenError("You may not read quotes.")
    items, _ = service.list_quotes(session, principal, QuoteFilters(limit=min(limit, 50)))
    return [
        {
            "id": str(x.id),
            "number": f"Q-{x.number:04d}",
            "status": x.status,
            "total": str(x.total),
            "account_id": str(x.account_id),
            "link": f"/quotes/{x.id}",
        }
        for x in items
    ]
