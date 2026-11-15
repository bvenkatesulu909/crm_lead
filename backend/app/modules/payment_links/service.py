"""Payment links (ADR 0031): create one for an invoice, list them, take in a verified webhook, and
turn a stored event into a payment.

The browser coming back from Razorpay changes nothing. Money is recorded only by ``apply_event``,
which runs in the worker for an event the webhook receiver verified and stored. Services never
commit; the router (or the worker) commits once.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish
from app.core.observability.metrics import PAYMENT_WEBHOOKS
from app.core.outbox import Job, PermanentJobError, enqueue
from app.modules.agents import api as agents_api
from app.modules.identity import api as identity_api
from app.modules.invoices import api as invoices_api
from app.modules.payment_links import rules, webhook
from app.modules.payment_links.models import PaymentEvent, PaymentLink
from app.modules.payment_links.provider import PaymentProvider, ProviderError
from app.modules.payment_links.schemas import PaymentLinkRead

ENTITY = "payment_link"
AGENT_KEY = "payment_links"
APPLY_JOB = "payment_link.apply"
MAX_BODY_BYTES = 64 * 1024


class InvoiceNotFoundError(NotFoundError):
    code = "invoice_not_found"

    def __init__(self) -> None:
        super().__init__("The invoice doesn't exist or isn't yours to see.")


class PaymentLinksUnavailableError(DomainError):
    status_code = 503
    code = "payment_links_unavailable"

    def __init__(self) -> None:
        super().__init__("Payment links are switched off for your organisation.")


class InvoiceNotPayableError(ConflictError):
    code = "invoice_not_payable"


class LinkRateLimitedError(DomainError):
    status_code = 429
    code = "payment_link_rate_limited"

    def __init__(self) -> None:
        super().__init__("Too many payment links were created. Try again later.")


class ProviderUnavailableError(DomainError):
    status_code = 503
    code = "payment_provider_unavailable"

    def __init__(self) -> None:
        super().__init__("The payment service could not be reached. Try again in a moment.")


class InvalidSignatureError(DomainError):
    status_code = 401
    code = "invalid_signature"

    def __init__(self) -> None:
        super().__init__("The signature is missing or wrong.")


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise ForbiddenError("Only members of an organisation can use payment links.")
    return principal.tenant_id, principal.user_id


def effective_status(link: PaymentLink, now: datetime) -> str:
    """An open link past its expiry reads as expired even before the provider tells us."""
    if link.status == "created" and link.expires_at <= now:
        return "expired"
    return link.status


def to_read(link: PaymentLink, now: datetime) -> PaymentLinkRead:
    return PaymentLinkRead(
        id=link.id,
        invoice_id=link.invoice_id,
        short_url=link.short_url,
        amount=rules.from_paise(link.amount_paise),
        currency=link.currency,
        status=effective_status(link, now),
        expires_at=link.expires_at,
        created_at=link.created_at,
        paid_at=link.paid_at,
    )


# --- staff: create and list ---------------------------------------------------------------


def create_link(
    session: Session,
    principal: Principal,
    provider: PaymentProvider,
    settings: Settings,
    invoice_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> PaymentLinkRead:
    when = now or datetime.now(UTC)
    tenant_id, user_id = _ids(principal)
    invoice = invoices_api.payable_invoice(session, principal, invoice_id)
    if invoice is None:
        raise InvoiceNotFoundError()
    if not invoices_api.can_record_payments(principal):
        raise ForbiddenError("You may view this invoice but not collect payments for it.")
    try:
        agents_api.check_can_call(session, tenant_id, AGENT_KEY, agents_api.Limits.default(), when)
    except agents_api.AgentUnavailableError:
        raise PaymentLinksUnavailableError() from None
    if invoice.status != "issued":
        raise InvoiceNotPayableError("Only an issued invoice can be paid.")
    if invoice.balance_due <= 0:
        raise InvoiceNotPayableError("This invoice has nothing left to pay.")
    if invoice.currency != rules.CURRENCY:
        raise InvoiceNotPayableError("UPI payments are for invoices in INR.")
    try:
        paise = rules.to_paise(invoice.balance_due)
    except ValueError as exc:
        raise InvoiceNotPayableError(str(exc)) from None

    recent = session.scalar(
        select(func.count())
        .select_from(PaymentLink)
        .where(
            PaymentLink.tenant_id == tenant_id,
            PaymentLink.created_by_user_id == user_id,
            PaymentLink.created_at > when - timedelta(hours=1),
        )
    )
    if (recent or 0) >= settings.razorpay_links_per_user_hour:
        raise LinkRateLimitedError()

    # One open link per invoice: a new one replaces the old. The provider may already have closed
    # the old link (paid or expired), which is fine - the local row is what the CRM trusts.
    open_link = session.scalars(
        select(PaymentLink)
        .where(
            PaymentLink.tenant_id == tenant_id,
            PaymentLink.invoice_id == invoice.id,
            PaymentLink.status == "created",
        )
        .with_for_update()
    ).one_or_none()
    if open_link is not None:
        try:
            provider.cancel_link(open_link.provider_link_id)
        except ProviderError:
            pass
        open_link.status = "cancelled"
        session.flush()

    attempt = (
        session.scalar(
            select(func.count())
            .select_from(PaymentLink)
            .where(PaymentLink.tenant_id == tenant_id, PaymentLink.invoice_id == invoice.id)
        )
        or 0
    ) + 1
    reference = rules.reference_id(invoice.id, attempt)
    expires = rules.expires_at(when, settings.razorpay_link_expiry_days)
    label = f"Invoice {invoice.number}" if invoice.number is not None else "Invoice"
    try:
        created = provider.create_link(
            reference_id=reference,
            amount_paise=paise,
            currency=rules.CURRENCY,
            description=label,
            expires_at=expires,
            notes={"invoice_id": str(invoice.id)},
        )
    except ProviderError:
        raise ProviderUnavailableError() from None

    link = PaymentLink(
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        created_by_user_id=user_id,
        provider_link_id=created.provider_link_id,
        reference_id=reference,
        short_url=created.short_url,
        amount_paise=paise,
        expires_at=expires,
    )
    session.add(link)
    try:
        session.flush()
    except IntegrityError:
        raise InvoiceNotPayableError("A payment link was just created. Reload the page.") from None
    record_audit(
        session,
        principal,
        action="payment_link.created",
        entity_type=ENTITY,
        entity_id=link.id,
        changes={"invoice_id": invoice.id, "amount_paise": paise, "reference_id": reference},
    )
    session.flush()
    session.refresh(link)
    return to_read(link, when)


def list_links(
    session: Session,
    principal: Principal,
    invoice_id: uuid.UUID,
    *,
    customer: bool,
    now: datetime | None = None,
) -> list[PaymentLinkRead]:
    """Staff see every link of an invoice they can read; a customer only the open one."""
    when = now or datetime.now(UTC)
    tenant_id, _ = _ids(principal)
    invoice = invoices_api.payable_invoice(session, principal, invoice_id)
    if invoice is None:
        raise InvoiceNotFoundError()
    links = session.scalars(
        select(PaymentLink)
        .where(PaymentLink.tenant_id == tenant_id, PaymentLink.invoice_id == invoice.id)
        .order_by(PaymentLink.created_at.desc())
        .limit(20)
    ).all()
    items = [to_read(link, when) for link in links]
    if customer:
        return [item for item in items if item.status == "created"][:1]
    return items


def link_creator(session: Session, tenant_id: uuid.UUID, link_id: uuid.UUID) -> uuid.UUID | None:
    """The person who created a link (they hear when it is paid)."""
    return session.scalar(
        select(PaymentLink.created_by_user_id).where(
            PaymentLink.tenant_id == tenant_id, PaymentLink.id == link_id
        )
    )


# --- the webhook --------------------------------------------------------------------------


def receive_webhook(
    session: Session,
    settings: Settings,
    raw_body: bytes,
    signature: str | None,
    event_id: str | None,
) -> str:
    """Check, store and queue one delivery. Returns what happened (for the metric); raises only for
    a bad signature. The caller commits."""
    secret = settings.razorpay_webhook_secret
    if not rules.verify_signature(
        raw_body, signature, secret.get_secret_value() if secret else None
    ):
        PAYMENT_WEBHOOKS.labels("bad_signature").inc()
        raise InvalidSignatureError()
    parsed = webhook.parse_event(raw_body)
    if parsed is None:
        PAYMENT_WEBHOOKS.labels("ignored").inc()
        return "ignored"
    tenant_id = session.scalar(
        text("select payment_link_tenant(:link_id)"), {"link_id": parsed.link_id}
    )
    if tenant_id is None:
        PAYMENT_WEBHOOKS.labels("unknown_link").inc()
        return "unknown_link"
    bind_tenant(session, tenant_id)
    link_id = session.scalar(
        select(PaymentLink.id).where(
            PaymentLink.tenant_id == tenant_id, PaymentLink.provider_link_id == parsed.link_id
        )
    )
    if link_id is None:
        PAYMENT_WEBHOOKS.labels("unknown_link").inc()
        return "unknown_link"
    provider_event_id = (event_id or "").strip()[:80] or f"body-{rules.body_sha256(raw_body)[:40]}"
    stored = session.scalar(
        insert(PaymentEvent)
        .values(
            tenant_id=tenant_id,
            payment_link_id=link_id,
            provider_event_id=provider_event_id,
            event_type=parsed.event_type,
            body_sha256=rules.body_sha256(raw_body),
            facts=parsed.facts,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "provider_event_id"])
        .returning(PaymentEvent.id)
    )
    if stored is None:
        PAYMENT_WEBHOOKS.labels("duplicate").inc()
        return "duplicate"
    enqueue(session, tenant_id=tenant_id, kind=APPLY_JOB, payload={"event_id": str(stored)})
    PAYMENT_WEBHOOKS.labels("stored").inc()
    return "stored"


# --- the worker ---------------------------------------------------------------------------


def apply_event(session: Session, job: Job) -> None:
    """Turn one stored event into a payment (or a note that a person must look). Safe to run twice:
    an event with an outcome is left alone, and the payment itself cannot be added twice."""
    try:
        event_id = uuid.UUID(str(job.payload["event_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("the job has no valid event id") from None
    event = session.scalars(
        select(PaymentEvent)
        .where(PaymentEvent.tenant_id == job.tenant_id, PaymentEvent.id == event_id)
        .with_for_update()
    ).one_or_none()
    if event is None:
        raise PermanentJobError("the event does not exist")
    if event.outcome is not None:
        return
    link = session.scalars(
        select(PaymentLink)
        .where(PaymentLink.tenant_id == job.tenant_id, PaymentLink.id == event.payment_link_id)
        .with_for_update()
    ).one()
    now = datetime.now(UTC)
    outcome = _decide(session, job.tenant_id, event, link, now)
    event.outcome = outcome
    event.processed_at = now
    session.flush()
    if outcome in {"amount_mismatch", "currency_mismatch", "invoice_closed"}:
        publish(
            session,
            job.tenant_id,
            "payment_link.needs_review",
            {
                "payment_link_id": str(link.id),
                "invoice_id": str(link.invoice_id),
                "reason": outcome,
            },
        )


def _decide(
    session: Session, tenant_id: uuid.UUID, event: PaymentEvent, link: PaymentLink, now: datetime
) -> str:
    if event.event_type in ("payment_link.expired", "payment_link.cancelled"):
        if link.status == "created":
            link.status = "expired" if event.event_type == "payment_link.expired" else "cancelled"
        return "ignored"
    if event.event_type != "payment_link.paid":
        return "ignored"
    facts = event.facts
    payment_id, paid_paise = facts.get("payment_id"), facts.get("amount_paise")
    if not isinstance(payment_id, str) or not isinstance(paid_paise, int):
        return "amount_mismatch"
    if facts.get("currency") != rules.CURRENCY:
        return "currency_mismatch"
    if paid_paise != link.amount_paise:
        return "amount_mismatch"
    robot = identity_api.automation_principal(session, tenant_id)
    result = invoices_api.record_gateway_payment(
        session,
        robot,
        link.invoice_id,
        amount=rules.from_paise(paid_paise),
        reference=payment_id,
    )
    if result != "applied":
        return result
    link.status = "paid"
    link.provider_payment_id = payment_id
    link.paid_at = now
    record_audit(
        session,
        robot,
        action="payment_link.paid",
        entity_type=ENTITY,
        entity_id=link.id,
        changes={"invoice_id": link.invoice_id, "amount_paise": paid_paise},
    )
    publish(
        session,
        tenant_id,
        "payment_link.paid",
        {"payment_link_id": str(link.id), "invoice_id": str(link.invoice_id)},
    )
    return "applied"
