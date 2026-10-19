"""Quote business rules. Functions here never commit: the router commits once.

- Lines are priced by the SERVER from the quote's price book; inactive products or products
  missing from the book are refused. Clients only choose quantity and a discount percentage.
- Submitting a quote with a line discount above the limit sends it for approval; otherwise it
  is approved straight away. Approvers never approve their own quotes (four-eyes), except
  tenant admins.
- Only drafts can be edited. Sent quotes are answered (accepted/declined) by the customer in
  the portal or recorded by staff; an expired quote can't be accepted.
- Every status change is written to quote_events and the audit log in the same transaction.
- Sending queues a "quote.pdf" job (outbox, ADR 0005); the worker stores the PDF - the version
  the customer received. Downloading creates it on the spot if the job hasn't run yet.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish as publish_event
from app.core.mail import Attachment, Mail, Mailer
from app.core.outbox import PermanentJobError, enqueue, latest_job_status
from app.core.storage import FileStore
from app.modules.accounts import api as accounts_api
from app.modules.catalog import api as catalog_api
from app.modules.contacts import api as contacts_api
from app.modules.documents import api as documents_api
from app.modules.identity import api as identity_api
from app.modules.orders import api as orders_api
from app.modules.quotes import repository, rules
from app.modules.quotes.models import Quote, QuoteEvent, QuoteLine, QuoteSettings
from app.modules.quotes.pdf import PdfLine, QuotePdfData, render_quote_pdf
from app.modules.quotes.repository import QuoteFilters
from app.modules.quotes.schemas import (
    PortalQuoteRead,
    QuoteCreate,
    QuoteEventRead,
    QuoteLineInput,
    QuoteLineRead,
    QuoteRead,
    QuoteSettingsRead,
    QuoteSettingsUpdate,
    QuoteUpdate,
)
from app.modules.sales import api as sales_api

ENTITY = "quote"
PDF_JOB = "quote.pdf"
# Status changes other modules may react to (domain events, ADR 0006).
QUOTE_EVENTS = {
    ("draft", "pending_approval"): "quote.approval_requested",
    ("pending_approval", "approved"): "quote.approved",
    ("pending_approval", "draft"): "quote.rejected",
    ("sent", "accepted"): "quote.accepted",
    ("sent", "declined"): "quote.declined",
}
EMAIL_JOB = "quote.email"
PDF_PURPOSE = "quote_pdf"


class QuoteNotFoundError(NotFoundError):
    code = "quote_not_found"

    def __init__(self) -> None:
        super().__init__("Quote not found.")


class RelatedNotFoundError(NotFoundError):
    code = "related_not_found"


class InvalidQuoteError(DomainError):
    status_code = 422
    code = "invalid_quote"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class QuoteNotSentError(ConflictError):
    code = "quote_not_sent"


class NoRecipientError(ConflictError):
    code = "quote_no_recipient"


class EmailPendingError(ConflictError):
    code = "email_pending"


class QuoteExpiredError(ConflictError):
    code = "quote_expired"


def _today() -> date:
    return datetime.now(UTC).date()


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ForbiddenError("Only members of an organisation can work with quotes.")
    return principal.tenant_id


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError("The quote was changed by someone else. Reload it.") from exc


def expired(quote: Quote) -> bool:
    return quote.status == "sent" and quote.valid_until < _today()


def _event(
    session: Session, principal: Principal, quote: Quote, old: str | None, note: str | None
) -> QuoteEvent:
    event = QuoteEvent(
        id=uuid.uuid4(),
        tenant_id=quote.tenant_id,
        quote_id=quote.id,
        from_status=old,
        to_status=quote.status,
        actor_user_id=principal.user_id,
        note=note,
    )
    session.add(event)
    record_audit(
        session,
        principal,
        action=f"quote.{quote.status}",
        entity_type=ENTITY,
        entity_id=quote.id,
        changes={"status": {"old": old, "new": quote.status}, "note": note},
    )
    return event


def _move(
    session: Session, principal: Principal, quote: Quote, target: str, note: str | None
) -> QuoteEvent:
    rules.check_transition(quote.status, target)
    old = quote.status
    quote.status = target
    event = _event(session, principal, quote, old, note)
    name = QUOTE_EVENTS.get((old, target))
    if name:
        publish_event(
            session,
            quote.tenant_id,
            name,
            {
                "quote_id": str(quote.id),
                "actor_id": str(principal.user_id) if principal.user_id else None,
            },
        )
    return event


# --- links and pricing --------------------------------------------------------------------


def _check_links(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    opportunity_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
) -> None:
    if opportunity_id is not None:
        visible, deal_account = sales_api.opportunity_account_id(session, principal, opportunity_id)
        if not visible:
            raise RelatedNotFoundError("Opportunity not found.")
        if deal_account != account_id:
            raise InvalidQuoteError("The opportunity belongs to another account.")
    if contact_id is not None:
        visible, contact_account = contacts_api.contact_account_id(session, principal, contact_id)
        if not visible:
            raise RelatedNotFoundError("Contact not found.")
        if contact_account != account_id:
            raise InvalidQuoteError("The contact works at another account.")


def _book(session: Session, tenant_id: uuid.UUID, book_id: uuid.UUID) -> catalog_api.BookInfo:
    book = catalog_api.price_book_info(session, tenant_id, book_id)
    if book is None:
        raise RelatedNotFoundError("Price book not found.")
    if not book.is_active:
        raise InvalidQuoteError("This price book is no longer active.")
    return book


def _price_lines(
    session: Session, quote: Quote, items: Sequence[QuoteLineInput]
) -> list[QuoteLine]:
    """Build lines with prices from the quote's price book (the only source of prices)."""
    # no_autoflush: the quote must be written ONCE, with its totals (one version step).
    with session.no_autoflush:
        prices = catalog_api.prices_for(
            session, quote.tenant_id, quote.price_book_id, [i.product_id for i in items]
        )
    lines: list[QuoteLine] = []
    for position, item in enumerate(items, start=1):
        price = prices.get(item.product_id)
        if price is None:
            raise InvalidQuoteError(f"Line {position}: this product is not in the price book.")
        if not price.product_active:
            raise InvalidQuoteError(f"Line {position}: {price.sku} is no longer sold.")
        money = rules.line_money(
            item.quantity, price.unit_price, item.discount_percent, price.tax_rate
        )
        lines.append(
            QuoteLine(
                tenant_id=quote.tenant_id,
                quote_id=quote.id,
                position=position,
                product_id=price.product_id,
                sku=price.sku,
                description=item.description or price.name,
                unit=price.unit,
                quantity=item.quantity,
                list_price=price.unit_price,
                discount_percent=item.discount_percent,
                net_unit_price=money.net_unit_price,
                tax_rate=price.tax_rate,
                line_gross=money.gross,
                line_discount=money.discount,
                line_subtotal=money.subtotal,
                line_tax=money.tax,
                line_total=money.total,
            )
        )
    return lines


def _normalised(items: Sequence[QuoteLineInput]) -> list[QuoteLineInput]:
    """Quantities and percentages in the form they are stored in (3 and 2 decimals)."""
    return [
        i.model_copy(
            update={
                "quantity": i.quantity.quantize(Decimal("0.001")),
                "discount_percent": i.discount_percent.quantize(Decimal("0.01")),
            }
        )
        for i in items
    ]


def _replace_lines(session: Session, quote: Quote, items: Sequence[QuoteLineInput]) -> None:
    """Re-price and replace all lines. All of the quote's own changes must be made BEFORE
    calling this: the DELETE below writes them in one UPDATE (one version step)."""
    items = _normalised(items)
    lines = _price_lines(session, quote, items)
    totals = rules.quote_money(
        [rules.line_money(i.quantity, ln.list_price, i.discount_percent, ln.tax_rate)
         for i, ln in zip(items, lines, strict=True)]
    )  # fmt: skip
    quote.gross_total = totals.gross
    quote.discount_total = totals.discount
    quote.subtotal = totals.subtotal
    quote.tax_total = totals.tax
    quote.total = totals.total
    quote.max_discount_percent = max((i.discount_percent for i in items), default=Decimal("0.00"))
    quote.needs_approval = rules.needs_approval(
        [i.discount_percent for i in items], approval_limit(session, quote.tenant_id)
    )
    repository.delete_lines(session, quote)
    session.add_all(lines)


def _inputs_of(session: Session, quote: Quote) -> list[QuoteLineInput]:
    return [
        QuoteLineInput(
            product_id=line.product_id,
            quantity=line.quantity,
            discount_percent=line.discount_percent,
            description=line.description,
        )
        for line in repository.lines_of(session, quote)
    ]


# --- create / edit ------------------------------------------------------------------------


def _may_quote_for(session: Session, principal: Principal, account_id: uuid.UUID) -> bool:
    if principal.has_permission(Permission.QUOTE_WRITE_ALL):
        return accounts_api.is_readable_account(session, principal, account_id)
    return accounts_api.is_owned_account(session, principal, account_id)


def _check_owner(session: Session, principal: Principal, owner_id: uuid.UUID) -> None:
    if owner_id != principal.user_id and not principal.has_permission(Permission.QUOTE_WRITE_ALL):
        raise ForbiddenError("You may not give quotes to other people.")
    if not identity_api.is_assignable_sales_user(session, _tenant(principal), owner_id):
        raise InvalidQuoteError("The owner must be an active sales employee of your organisation.")


def create_quote(session: Session, principal: Principal, data: QuoteCreate) -> Quote:
    tenant_id = _tenant(principal)
    if principal.user_type != "staff" or not (
        principal.has_permission(Permission.QUOTE_WRITE_ALL)
        or principal.has_permission(Permission.QUOTE_WRITE_OWN)
    ):
        raise ForbiddenError("You may not create quotes.")
    if not _may_quote_for(session, principal, data.account_id):
        raise RelatedNotFoundError("Account not found.")
    _check_links(session, principal, data.account_id, data.opportunity_id, data.contact_id)
    book = _book(session, tenant_id, data.price_book_id)
    if data.owner_id is not None:
        _check_owner(session, principal, data.owner_id)
    valid_until = data.valid_until or _today() + timedelta(days=rules.DEFAULT_VALIDITY_DAYS)
    if valid_until < _today():
        raise InvalidQuoteError("The validity date can't be in the past.")
    quote = Quote(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        number=repository.next_quote_number(session, tenant_id),
        revision=1,
        title=data.title,
        account_id=data.account_id,
        opportunity_id=data.opportunity_id,
        contact_id=data.contact_id,
        owner_id=data.owner_id or principal.user_id,
        created_by_user_id=principal.user_id,
        price_book_id=book.id,
        currency=book.currency,
        status="draft",
        valid_until=valid_until,
        customer_note=data.customer_note,
        internal_note=data.internal_note,
    )
    session.add(quote)
    _replace_lines(session, quote, data.lines)
    _event(session, principal, quote, None, None)
    _flush(session)
    return quote


def _load_for_change(session: Session, principal: Principal, quote_id: uuid.UUID) -> Quote:
    quote = repository.get_writable(session, principal, quote_id)
    if quote is None:
        if repository.get_readable(session, principal, quote_id) is not None:
            raise ForbiddenError("You may view this quote but not change it.")
        raise QuoteNotFoundError()
    return quote


def _check_version(quote: Quote, version: int) -> None:
    if quote.version != version:
        raise VersionConflictError(
            f"The quote was changed by someone else (now version {quote.version}). Reload it."
        )


def update_quote(
    session: Session, principal: Principal, quote_id: uuid.UUID, data: QuoteUpdate
) -> Quote:
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, data.version)
    if quote.status != "draft":
        raise rules.QuoteStateError("Only draft quotes can be changed. Revise it instead.")
    fields = data.model_fields_set - {"version", "lines"}
    opportunity = data.opportunity_id if "opportunity_id" in fields else quote.opportunity_id
    contact = data.contact_id if "contact_id" in fields else quote.contact_id
    _check_links(session, principal, quote.account_id, opportunity, contact)
    if "owner_id" in fields and data.owner_id != quote.owner_id:
        if not principal.has_permission(Permission.QUOTE_WRITE_ALL):
            raise ForbiddenError("Only managers and administrators can change the owner.")
        if data.owner_id is not None:
            _check_owner(session, principal, data.owner_id)
    if data.valid_until is not None and data.valid_until < _today():
        raise InvalidQuoteError("The validity date can't be in the past.")
    items = data.lines if data.lines is not None else _inputs_of(session, quote)
    if data.price_book_id is not None and data.price_book_id != quote.price_book_id:
        book = _book(session, quote.tenant_id, data.price_book_id)
        quote.price_book_id, quote.currency = book.id, book.currency
    for field in fields - {"price_book_id"}:
        setattr(quote, field, getattr(data, field))
    _replace_lines(session, quote, items)
    record_audit(
        session,
        principal,
        action="quote.updated",
        entity_type=ENTITY,
        entity_id=quote.id,
        changes={"fields": sorted(fields | ({"lines"} if data.lines is not None else set()))},
    )
    _flush(session)
    return quote


# --- workflow -----------------------------------------------------------------------------


def submit(
    session: Session, principal: Principal, quote_id: uuid.UUID, *, version: int, note: str | None
) -> Quote:
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    inputs = _inputs_of(session, quote)
    if not inputs:
        raise InvalidQuoteError("Add at least one line before submitting.")
    quote.submitted_at = datetime.now(UTC)
    if rules.needs_approval(
        [i.discount_percent for i in inputs], approval_limit(session, quote.tenant_id)
    ):
        _move(session, principal, quote, "pending_approval", note)
    else:
        quote.approved_at = quote.submitted_at
        _move(session, principal, quote, "approved", note or "No approval needed")
    # Re-price on submit: prices may have changed since the draft was saved.
    _replace_lines(session, quote, inputs)
    _flush(session)
    return quote


def approve(
    session: Session, principal: Principal, quote_id: uuid.UUID, *, version: int, note: str | None
) -> Quote:
    if not principal.has_permission(Permission.QUOTE_APPROVE):
        raise ForbiddenError("You may not approve quotes.")
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    own = principal.user_id in (quote.owner_id, quote.created_by_user_id)
    if own and Role.TENANT_ADMIN not in principal.roles:
        raise ForbiddenError("Another manager must approve your own quote (four-eyes rule).")
    quote.approved_at = datetime.now(UTC)
    quote.approved_by_user_id = principal.user_id
    _move(session, principal, quote, "approved", note)
    _flush(session)
    return quote


def reject(
    session: Session, principal: Principal, quote_id: uuid.UUID, *, version: int, reason: str
) -> Quote:
    if not principal.has_permission(Permission.QUOTE_APPROVE):
        raise ForbiddenError("You may not reject quotes.")
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    quote.submitted_at = None
    _move(session, principal, quote, "draft", f"Returned: {reason}")
    _flush(session)
    return quote


def send(
    session: Session, principal: Principal, quote_id: uuid.UUID, *, version: int, note: str | None
) -> Quote:
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    _send(session, principal, quote, note)
    _flush(session)
    return quote


def _send(session: Session, principal: Principal, quote: Quote, note: str | None) -> QuoteEvent:
    if quote.valid_until < _today():
        raise QuoteExpiredError("The validity date has passed. Revise the quote first.")
    quote.sent_at = datetime.now(UTC)
    event = _move(session, principal, quote, "sent", note)
    # Saved together with the status: a sent quote always gets its PDF.
    enqueue(session, tenant_id=quote.tenant_id, kind=PDF_JOB, payload={"quote_id": str(quote.id)})
    return event


def _decide(
    session: Session, principal: Principal, quote: Quote, target: str, note: str | None
) -> Quote:
    if expired(quote) and target == "accepted":
        raise QuoteExpiredError("This quote has expired and can no longer be accepted.")
    quote.decided_at = datetime.now(UTC)
    quote.decision_note = note
    _move(session, principal, quote, target, note)
    _flush(session)
    return quote


def record_decision(
    session: Session,
    principal: Principal,
    quote_id: uuid.UUID,
    *,
    version: int,
    accepted: bool,
    note: str | None,
) -> Quote:
    """Staff record the customer's answer (e.g. given by phone or signed on paper)."""
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    return _decide(session, principal, quote, "accepted" if accepted else "declined", note)


def customer_decision(
    session: Session,
    principal: Principal,
    quote_id: uuid.UUID,
    *,
    version: int,
    accepted: bool,
    note: str | None,
) -> Quote:
    """The customer answers in the portal - only for their own company's sent quotes."""
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_QUOTE_RESPOND
    ):
        raise ForbiddenError("Only customers can answer quotes here.")
    quote = repository.get_for_customer_decision(session, principal, quote_id)
    if quote is None:
        raise QuoteNotFoundError()
    _check_version(quote, version)
    return _decide(session, principal, quote, "accepted" if accepted else "declined", note)


def revise(session: Session, principal: Principal, quote_id: uuid.UUID, *, version: int) -> Quote:
    """New draft revision (QT-0007/2) with the same lines, re-priced; the old one is superseded."""
    old = _load_for_change(session, principal, quote_id)
    _check_version(old, version)
    if old.status not in rules.REVISABLE:
        raise rules.QuoteStateError(f"A {old.status} quote cannot be revised.")
    inputs = _inputs_of(session, old)
    previous = old.status
    old.status = "superseded"
    _event(session, principal, old, previous, "Replaced by a new revision")
    new = Quote(
        id=uuid.uuid4(),
        tenant_id=old.tenant_id,
        number=old.number,
        revision=old.revision + 1,
        revision_of_id=old.id,
        title=old.title,
        account_id=old.account_id,
        opportunity_id=old.opportunity_id,
        contact_id=old.contact_id,
        owner_id=old.owner_id,
        created_by_user_id=principal.user_id,
        price_book_id=old.price_book_id,
        currency=old.currency,
        status="draft",
        valid_until=max(old.valid_until, _today() + timedelta(days=rules.DEFAULT_VALIDITY_DAYS)),
        customer_note=old.customer_note,
        internal_note=old.internal_note,
    )
    session.add(new)
    _replace_lines(session, new, inputs)
    _event(session, principal, new, None, f"Revision of version {old.revision}")
    _flush(session)
    return new


def convert_to_order(
    session: Session,
    principal: Principal,
    quote_id: uuid.UUID,
    *,
    version: int,
    customer_reference: str | None,
) -> tuple[Quote, int]:
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    if quote.status != "accepted":
        raise rules.QuoteStateError("Only an accepted quote can become an order.")
    if quote.order_id is not None:
        raise rules.QuoteStateError("This quote already has an order.")
    order_id, number = orders_api.create_order_from_quote(
        session,
        principal,
        account_id=quote.account_id,
        currency=quote.currency,
        customer_reference=customer_reference,
        internal_note=f"From quote QT-{quote.number:04d}/{quote.revision}",
        lines=[
            orders_api.NewOrderLine(
                product_code=line.sku,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.net_unit_price,
                tax_rate=line.tax_rate,
            )
            for line in repository.lines_of(session, quote)
        ],
    )
    quote.order_id = order_id
    record_audit(
        session,
        principal,
        action="quote.converted",
        entity_type=ENTITY,
        entity_id=quote.id,
        changes={"order_id": order_id, "order_number": number},
    )
    _flush(session)
    return quote, number


# --- read ---------------------------------------------------------------------------------


def get_quote(session: Session, principal: Principal, quote_id: uuid.UUID) -> Quote:
    quote = repository.get_readable(session, principal, quote_id)
    if quote is None:
        raise QuoteNotFoundError()
    return quote


def list_quotes(
    session: Session, principal: Principal, filters: QuoteFilters
) -> tuple[Sequence[Quote], int]:
    return repository.search(session, principal, filters)


def _columns(quote: Quote) -> dict[str, object]:
    return {c.key: getattr(quote, c.key) for c in Quote.__table__.columns}


def to_read(session: Session, quote: Quote) -> QuoteRead:
    return QuoteRead.model_validate(
        {
            **_columns(quote),
            "expired": expired(quote),
            "email_status": email_status(session, quote),
            "lines": [
                QuoteLineRead.model_validate(ln) for ln in repository.lines_of(session, quote)
            ],
        }
    )


def to_portal(session: Session, quote: Quote) -> PortalQuoteRead:
    return PortalQuoteRead.model_validate(
        {
            **_columns(quote),
            "expired": expired(quote),
            "lines": [
                QuoteLineRead.model_validate(ln) for ln in repository.lines_of(session, quote)
            ],
        }
    )


def summary_values(quote: Quote) -> dict[str, object]:
    return {**_columns(quote), "expired": expired(quote)}


def history(session: Session, principal: Principal, quote_id: uuid.UUID) -> list[QuoteEventRead]:
    quote = get_quote(session, principal, quote_id)
    events = repository.events_of(session, quote)
    people = identity_api.people_by_id(
        session, quote.tenant_id, {e.actor_user_id for e in events if e.actor_user_id}
    )
    return [
        QuoteEventRead(
            from_status=e.from_status,
            to_status=e.to_status,
            note=e.note,
            created_at=e.created_at,
            actor_name=people.get(e.actor_user_id, ("Former user", ""))[0]
            if e.actor_user_id
            else None,
        )
        for e in events
    ]


# --- PDF (ADR 0005) -----------------------------------------------------------------------


def number_label(quote: Quote) -> str:
    base = f"QT-{quote.number:04d}"
    return f"{base} rev {quote.revision}" if quote.revision > 1 else base


def pdf_file_name(quote: Quote) -> str:
    return number_label(quote).replace(" rev ", "-rev") + ".pdf"


def _pdf_data(session: Session, quote: Quote) -> QuotePdfData:
    t = quote.tenant_id
    assert quote.sent_at is not None  # noqa: S101 - checked by the callers
    return QuotePdfData(
        number=number_label(quote),
        title=quote.title,
        supplier=identity_api.tenant_name(session, t) or "Supplier",
        customer=accounts_api.account_name(session, t, quote.account_id) or "Customer",
        contact=contacts_api.contact_name(session, t, quote.contact_id)
        if quote.contact_id
        else None,
        issued=quote.sent_at.date(),
        valid_until=quote.valid_until,
        currency=quote.currency,
        lines=tuple(
            PdfLine(
                ln.position,
                ln.sku,
                ln.description,
                ln.quantity,
                ln.unit,
                ln.list_price,
                ln.discount_percent,
                ln.net_unit_price,
                ln.tax_rate,
                ln.line_subtotal,
            )
            for ln in repository.lines_of(session, quote)
        ),
        gross_total=quote.gross_total,
        discount_total=quote.discount_total,
        subtotal=quote.subtotal,
        tax_total=quote.tax_total,
        total=quote.total,
        customer_note=quote.customer_note,
    )


def ensure_pdf(
    session: Session, store: FileStore, quote: Quote, created_by: uuid.UUID | None
) -> documents_api.DocumentInfo:
    """The quote's stored PDF, created once. Only quotes that were sent have one: their content
    can't change any more (changes need a new revision, which gets its own PDF)."""
    if quote.sent_at is None:
        raise QuoteNotSentError("A PDF is available once the quote has been sent.")
    existing = documents_api.find_document(session, quote.tenant_id, ENTITY, quote.id, PDF_PURPOSE)
    if existing is not None:
        return existing
    return documents_api.store_generated_document(
        session,
        store,
        tenant_id=quote.tenant_id,
        record_type=ENTITY,
        record_id=quote.id,
        purpose=PDF_PURPOSE,
        file_name=pdf_file_name(quote),
        content_type="application/pdf",
        data=render_quote_pdf(_pdf_data(session, quote)),
        customer_visible=True,
        created_by_user_id=created_by,
    )


def quote_pdf(
    session: Session, principal: Principal, store: FileStore, quote_id: uuid.UUID
) -> tuple[documents_api.DocumentInfo, bytes]:
    """Download for staff and customers: the usual read policy decides (404 otherwise)."""
    quote = get_quote(session, principal, quote_id)
    info = ensure_pdf(session, store, quote, principal.user_id)
    return documents_api.read_document(session, store, quote.tenant_id, info.id)


def run_pdf_job(
    session: Session, store: FileStore, tenant_id: uuid.UUID, quote_id: uuid.UUID
) -> None:
    quote = repository.get_in_tenant(session, tenant_id, quote_id)
    if quote is None:
        raise PermanentJobError("quote not found")
    if quote.sent_at is None:
        raise PermanentJobError("quote was not sent")
    ensure_pdf(session, store, quote, None)


# --- e-mail (ADR 0005, step E2b) ------------------------------------------------------------

EMAIL_STATUS = {"pending": "sending", "running": "sending", "done": "sent", "dead": "failed"}
EMAIL_DEFAULT_NOTES = ("Sent by e-mail", "E-mailed again")


def email_status(session: Session, quote: Quote) -> str | None:
    """'sending' / 'sent' / 'failed' for the newest e-mail of this quote, None if never."""
    status = latest_job_status(session, quote.tenant_id, EMAIL_JOB, "quote_id", str(quote.id))
    return EMAIL_STATUS.get(status) if status else None


def email_quote(
    session: Session,
    principal: Principal,
    quote_id: uuid.UUID,
    *,
    version: int,
    message: str | None,
) -> Quote:
    """Send the quote to its contact by e-mail, with the PDF attached.

    An approved quote becomes "sent"; a sent quote can be e-mailed again (e.g. the customer
    lost it). The e-mail itself goes out from the worker, so the mail server can't make this
    request slow or fail. The message is kept in the quote history.
    """
    quote = _load_for_change(session, principal, quote_id)
    _check_version(quote, version)
    if quote.contact_id is None or not contacts_api.contact_email(
        session, quote.tenant_id, quote.contact_id
    ):
        raise NoRecipientError(
            "Choose a contact with an e-mail address for this quote first (edit the draft or "
            "revise the quote)."
        )
    if quote.status == "sent":
        if email_status(session, quote) == "sending":
            raise EmailPendingError("An e-mail for this quote is already on its way.")
        event = _event(session, principal, quote, "sent", message or EMAIL_DEFAULT_NOTES[1])
        quote.updated_at = datetime.now(UTC)  # bumps the version: a double click gets a 409
    elif quote.status == "approved":
        event = _send(session, principal, quote, message or EMAIL_DEFAULT_NOTES[0])
    else:
        raise rules.QuoteStateError("Only approved or sent quotes can be e-mailed.")
    enqueue(
        session,
        tenant_id=quote.tenant_id,
        kind=EMAIL_JOB,
        payload={"quote_id": str(quote.id), "event_id": str(event.id)},
    )
    _flush(session)
    return quote


def _system_event(session: Session, quote: Quote, note: str) -> None:
    # Written by the worker (no signed-in user), so there is no audit row (it needs a person).
    session.add(
        QuoteEvent(
            tenant_id=quote.tenant_id,
            quote_id=quote.id,
            from_status=quote.status,
            to_status=quote.status,
            actor_user_id=None,
            note=note[:500],
        )
    )


def mail_text(
    *, contact: str, supplier: str, quote: Quote, message: str | None, portal_url: str
) -> str:
    parts = [f"Hello {contact}," if contact else "Hello,", ""]
    if message:
        parts += [message, ""]
    parts += [
        f"Please find attached our quote {number_label(quote)}: {quote.title}.",
        f"Total: {quote.total:,.2f} {quote.currency}, valid until {quote.valid_until.isoformat()}.",
        "",
        f"You can view and answer it in our customer portal: {portal_url}",
        "",
        "Kind regards,",
        supplier,
    ]
    return "\n".join(parts)


def run_email_job(
    session: Session,
    store: FileStore,
    mailer: Mailer,
    *,
    tenant_id: uuid.UUID,
    quote_id: uuid.UUID,
    event_id: uuid.UUID,
    web_app_url: str,
) -> None:
    quote = repository.get_in_tenant(session, tenant_id, quote_id)
    if quote is None:
        raise PermanentJobError("quote not found")
    if quote.status not in rules.CUSTOMER_VISIBLE:
        raise PermanentJobError("the quote is no longer sent")
    recipient = (
        contacts_api.contact_email(session, tenant_id, quote.contact_id)
        if quote.contact_id
        else None
    )
    if recipient is None:
        raise PermanentJobError("the contact has no e-mail address")
    name, address = recipient
    note = session.scalar(
        select(QuoteEvent.note).where(QuoteEvent.tenant_id == tenant_id, QuoteEvent.id == event_id)
    )
    message = None if note in EMAIL_DEFAULT_NOTES else note
    info = ensure_pdf(session, store, quote, None)
    _, pdf = documents_api.read_document(session, store, tenant_id, info.id)
    supplier = identity_api.tenant_name(session, tenant_id) or "Your supplier"
    owner_email = (
        identity_api.staff_email(session, tenant_id, quote.owner_id) if quote.owner_id else None
    )
    mailer.send(
        Mail(
            to=(address,),
            subject=f"Quote {number_label(quote)}: {quote.title}",
            text=mail_text(
                contact=name,
                supplier=supplier,
                quote=quote,
                message=message,
                portal_url=f"{web_app_url.rstrip('/')}/portal/quotes/{quote.id}",
            ),
            attachments=(Attachment(info.file_name, "application/pdf", pdf),),
            reply_to=owner_email,
        )
    )
    _system_event(session, quote, f"E-mail sent to {name or 'the contact'}")


FAILURE_TEXT = {
    "MailRejectedError": "the mail server refused the address",
    "PermanentJobError: the contact has no e-mail address": "the contact has no e-mail address",
    "PermanentJobError: the quote is no longer sent": "the quote is no longer sent",
}


def email_failed(session: Session, tenant_id: uuid.UUID, quote_id: uuid.UUID, error: str) -> None:
    quote = repository.get_in_tenant(session, tenant_id, quote_id)
    if quote is not None:
        reason = FAILURE_TEXT.get(error, "please try again, or send it another way")
        _system_event(session, quote, f"E-mail could not be sent: {reason}")


# --- organisation settings (step E2c) ---------------------------------------------------------


def _settings_row(
    session: Session, tenant_id: uuid.UUID, *, lock: bool = False
) -> QuoteSettings | None:
    query = select(QuoteSettings).where(QuoteSettings.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update()
    return session.scalars(query).one_or_none()


def approval_limit(session: Session, tenant_id: uuid.UUID) -> Decimal:
    """The organisation's limit: line discounts above it need a manager's approval."""
    row = _settings_row(session, tenant_id)
    return row.approval_limit_percent if row else rules.DEFAULT_APPROVAL_LIMIT


def _settings_read(row: QuoteSettings | None) -> QuoteSettingsRead:
    if row is None:
        return QuoteSettingsRead(
            approval_limit_percent=rules.DEFAULT_APPROVAL_LIMIT, version=0, updated_at=None
        )
    return QuoteSettingsRead(
        approval_limit_percent=row.approval_limit_percent,
        version=row.version,
        updated_at=row.updated_at,
    )


def get_settings(session: Session, principal: Principal) -> QuoteSettingsRead:
    return _settings_read(_settings_row(session, _tenant(principal)))


def update_settings(
    session: Session, principal: Principal, data: QuoteSettingsUpdate
) -> QuoteSettingsRead:
    """Tenant admins change the approval limit. It applies to quotes submitted from now on;
    quotes already waiting for approval keep waiting."""
    if not principal.has_permission(Permission.QUOTE_SETTINGS_MANAGE):
        raise ForbiddenError("Only administrators can change quote settings.")
    tenant_id = _tenant(principal)
    row = _settings_row(session, tenant_id, lock=True)
    current = row.version if row else 0
    if data.version != current:
        raise VersionConflictError("The settings were changed by someone else. Reload them.")
    old = row.approval_limit_percent if row else rules.DEFAULT_APPROVAL_LIMIT
    new = data.approval_limit_percent.quantize(Decimal("0.01"))
    if row is None:
        row = QuoteSettings(tenant_id=tenant_id, approval_limit_percent=new)
        session.add(row)
    row.approval_limit_percent = new
    row.updated_by_user_id = principal.user_id
    record_audit(
        session,
        principal,
        action="quote.settings_changed",
        entity_type="quote_settings",
        entity_id=tenant_id,
        changes={"approval_limit_percent": {"old": old, "new": new}},
    )
    _flush(session)
    session.refresh(row)
    return _settings_read(row)
