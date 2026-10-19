"""Quote endpoints: staff at /api/v1/quotes, customers at /api/v1/portal/quotes.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.storage import FileStore, get_file_store
from app.modules.identity.api import require_any_permission
from app.modules.quotes import service
from app.modules.quotes.repository import QuoteFilters
from app.modules.quotes.schemas import (
    ConvertToOrder,
    EmailQuote,
    PortalQuotePage,
    PortalQuoteRead,
    PortalQuoteSummary,
    QuoteCreate,
    QuoteEventRead,
    QuotePage,
    QuoteRead,
    QuoteSettingsRead,
    QuoteSettingsUpdate,
    QuoteStatus,
    QuoteSummary,
    QuoteUpdate,
    Step,
    StepWithReason,
)

router = APIRouter(prefix="/quotes", tags=["quotes"], responses=problem_responses(401, 403))
portal_router = APIRouter(
    prefix="/portal/quotes", tags=["portal"], responses=problem_responses(401, 403)
)
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.QUOTE_READ_ALL, Permission.QUOTE_READ_OWN)),
]
Writer = Annotated[
    Principal,
    Depends(require_any_permission(Permission.QUOTE_WRITE_ALL, Permission.QUOTE_WRITE_OWN)),
]
Approver = Annotated[Principal, Depends(require_any_permission(Permission.QUOTE_APPROVE))]
SettingsAdmin = Annotated[
    Principal, Depends(require_any_permission(Permission.QUOTE_SETTINGS_MANAGE))
]
Customer = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_QUOTE_READ))]
CustomerResponder = Annotated[
    Principal, Depends(require_any_permission(Permission.PORTAL_QUOTE_RESPOND))
]
Db = Annotated[Session, Depends(get_db_session)]
Files = Annotated[FileStore, Depends(get_file_store)]
PDF = problem_responses(404, 409, 503)
STEP = problem_responses(404, 409, 422)


@router.get("", summary="List quotes you may see (newest first; superseded hidden)")
def list_quotes(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    quote_status: Annotated[list[QuoteStatus] | None, Query(alias="status")] = None,
    account_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    include_superseded: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> QuotePage:
    filters = QuoteFilters(
        q=q,
        statuses=tuple(quote_status or ()),
        account_id=account_id,
        opportunity_id=opportunity_id,
        order_id=order_id,
        owner_id=owner_id,
        include_superseded=include_superseded,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_quotes(session, principal, filters)
    return QuotePage(
        items=[QuoteSummary.model_validate(service.summary_values(x)) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft quote (prices come from the price book)",
    responses=problem_responses(404, 422),
)
def create_quote(
    data: QuoteCreate, principal: Writer, session: Db, response: Response
) -> QuoteRead:
    quote = service.create_quote(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/quotes/{quote.id}"
    return service.to_read(session, quote)


@router.get("/settings", summary="Your organisation's quote settings (approval limit)")
def quote_settings(principal: Reader, session: Db) -> QuoteSettingsRead:
    return service.get_settings(session, principal)


@router.put(
    "/settings",
    summary="Change the approval limit (tenant admins)",
    responses=problem_responses(409, 422),
)
def update_quote_settings(
    data: QuoteSettingsUpdate, principal: SettingsAdmin, session: Db
) -> QuoteSettingsRead:
    result = service.update_settings(session, principal, data)
    session.commit()
    return result


@router.get("/{quote_id}", summary="Get one quote with its lines", responses=problem_responses(404))
def get_quote(quote_id: uuid.UUID, principal: Reader, session: Db) -> QuoteRead:
    return service.to_read(session, service.get_quote(session, principal, quote_id))


@router.get(
    "/{quote_id}/history", summary="Status history (newest first)", responses=problem_responses(404)
)
def history(quote_id: uuid.UUID, principal: Reader, session: Db) -> list[QuoteEventRead]:
    return service.history(session, principal, quote_id)


@router.patch("/{quote_id}", summary="Change a draft quote", responses=STEP)
def update_quote(
    quote_id: uuid.UUID, data: QuoteUpdate, principal: Writer, session: Db
) -> QuoteRead:
    quote = service.update_quote(session, principal, quote_id, data)
    session.commit()
    return service.to_read(session, quote)


@router.post(
    "/{quote_id}/submit",
    summary="Submit: approved at once, or sent for approval if a discount is above the limit",
    responses=STEP,
)
def submit(quote_id: uuid.UUID, data: Step, principal: Writer, session: Db) -> QuoteRead:
    quote = service.submit(session, principal, quote_id, version=data.version, note=data.note)
    session.commit()
    return service.to_read(session, quote)


@router.post(
    "/{quote_id}/approve",
    summary="Approve (managers; never your own quote unless you are a tenant admin)",
    responses=STEP,
)
def approve(quote_id: uuid.UUID, data: Step, principal: Approver, session: Db) -> QuoteRead:
    quote = service.approve(session, principal, quote_id, version=data.version, note=data.note)
    session.commit()
    return service.to_read(session, quote)


@router.post(
    "/{quote_id}/reject", summary="Return to draft with a reason (managers)", responses=STEP
)
def reject(
    quote_id: uuid.UUID, data: StepWithReason, principal: Approver, session: Db
) -> QuoteRead:
    quote = service.reject(session, principal, quote_id, version=data.version, reason=data.reason)
    session.commit()
    return service.to_read(session, quote)


@router.post("/{quote_id}/send", summary="Mark as sent to the customer", responses=STEP)
def send(quote_id: uuid.UUID, data: Step, principal: Writer, session: Db) -> QuoteRead:
    quote = service.send(session, principal, quote_id, version=data.version, note=data.note)
    session.commit()
    return service.to_read(session, quote)


@router.post(
    "/{quote_id}/email",
    summary="E-mail the quote with its PDF to the quote's contact (approved or sent quotes)",
    responses=STEP,
)
def email_quote(quote_id: uuid.UUID, data: EmailQuote, principal: Writer, session: Db) -> QuoteRead:
    quote = service.email_quote(
        session, principal, quote_id, version=data.version, message=data.message
    )
    session.commit()
    return service.to_read(session, quote)


@router.post("/{quote_id}/accept", summary="Record that the customer accepted", responses=STEP)
def accept(quote_id: uuid.UUID, data: Step, principal: Writer, session: Db) -> QuoteRead:
    quote = service.record_decision(
        session, principal, quote_id, version=data.version, accepted=True, note=data.note
    )
    session.commit()
    return service.to_read(session, quote)


@router.post("/{quote_id}/decline", summary="Record that the customer declined", responses=STEP)
def decline(quote_id: uuid.UUID, data: StepWithReason, principal: Writer, session: Db) -> QuoteRead:
    quote = service.record_decision(
        session, principal, quote_id, version=data.version, accepted=False, note=data.reason
    )
    session.commit()
    return service.to_read(session, quote)


@router.post(
    "/{quote_id}/revise",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new draft revision; this one becomes superseded",
    responses=STEP,
)
def revise(quote_id: uuid.UUID, data: Step, principal: Writer, session: Db) -> QuoteRead:
    quote = service.revise(session, principal, quote_id, version=data.version)
    session.commit()
    return service.to_read(session, quote)


@router.post(
    "/{quote_id}/order",
    status_code=status.HTTP_201_CREATED,
    summary="Turn an accepted quote into a draft order (once)",
    responses=STEP,
)
def convert(quote_id: uuid.UUID, data: ConvertToOrder, principal: Writer, session: Db) -> QuoteRead:
    quote, _ = service.convert_to_order(
        session,
        principal,
        quote_id,
        version=data.version,
        customer_reference=data.customer_reference,
    )
    session.commit()
    return service.to_read(session, quote)


# --- customer portal -------------------------------------------------------------------------


@portal_router.get("", summary="Quotes sent to my company")
def my_quotes(principal: Customer, session: Db) -> PortalQuotePage:
    items, total = service.list_quotes(session, principal, QuoteFilters(limit=200))
    return PortalQuotePage(
        items=[PortalQuoteSummary.model_validate(service.summary_values(x)) for x in items],
        total=total,
    )


@portal_router.get("/{quote_id}", summary="One of my quotes", responses=problem_responses(404))
def my_quote(quote_id: uuid.UUID, principal: Customer, session: Db) -> PortalQuoteRead:
    return service.to_portal(session, service.get_quote(session, principal, quote_id))


@portal_router.post(
    "/{quote_id}/accept", summary="Accept a quote sent to my company", responses=STEP
)
def accept_quote(
    quote_id: uuid.UUID, data: Step, principal: CustomerResponder, session: Db
) -> PortalQuoteRead:
    quote = service.customer_decision(
        session, principal, quote_id, version=data.version, accepted=True, note=data.note
    )
    session.commit()
    return service.to_portal(session, quote)


@portal_router.post("/{quote_id}/decline", summary="Decline a quote, saying why", responses=STEP)
def decline_quote(
    quote_id: uuid.UUID, data: StepWithReason, principal: CustomerResponder, session: Db
) -> PortalQuoteRead:
    quote = service.customer_decision(
        session, principal, quote_id, version=data.version, accepted=False, note=data.reason
    )
    session.commit()
    return service.to_portal(session, quote)


def _pdf_response(file_name: str, data: bytes) -> Response:
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{quote_id}/pdf",
    summary="Download the PDF of a sent quote",
    response_class=Response,
    responses={**PDF, 200: {"content": {"application/pdf": {}}}},
)
def quote_pdf(quote_id: uuid.UUID, principal: Reader, session: Db, files: Files) -> Response:
    info, data = service.quote_pdf(session, principal, files, quote_id)
    session.commit()  # keeps the document row if it was created just now
    return _pdf_response(info.file_name, data)


@portal_router.get(
    "/{quote_id}/pdf",
    summary="Download the PDF of one of my quotes",
    response_class=Response,
    responses={**PDF, 200: {"content": {"application/pdf": {}}}},
)
def my_quote_pdf(quote_id: uuid.UUID, principal: Customer, session: Db, files: Files) -> Response:
    info, data = service.quote_pdf(session, principal, files, quote_id)
    session.commit()
    return _pdf_response(info.file_name, data)
