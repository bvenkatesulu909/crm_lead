"""Payment link endpoints (ADR 0031): staff create and list, the portal customer lists the open
link of their own invoice, and Razorpay's webhook arrives. Thin: gate, call the service, commit."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import DomainError, problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.payment_links import service
from app.modules.payment_links.provider import PaymentProvider
from app.modules.payment_links.schemas import CreatePaymentLink, PaymentLinkList, PaymentLinkRead

Db = Annotated[Session, Depends(get_db_session)]

# --- staff --------------------------------------------------------------------------------

router = APIRouter(
    prefix="/payment-links", tags=["payment-links"], responses=problem_responses(401, 403)
)
Reader = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.INVOICE_READ_ALL, Permission.INVOICE_READ_OWN_ACCOUNTS)
    ),
]
Cashier = Annotated[Principal, Depends(require_any_permission(Permission.PAYMENT_RECORD))]


def _provider(request: Request) -> PaymentProvider:
    provider: PaymentProvider = request.app.state.payment_provider
    return provider


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a UPI payment link for the balance of an issued invoice",
    description="Only the invoice is sent. The amount, reference and expiry are decided by the "
    "server, and a new link replaces the invoice's open one.",
    responses=problem_responses(404, 409, 422, 429, 503),
)
def create_link(
    data: CreatePaymentLink, request: Request, principal: Cashier, session: Db
) -> PaymentLinkRead:
    link = service.create_link(
        session, principal, _provider(request), _settings(request), data.invoice_id
    )
    session.commit()
    return link


@router.get(
    "",
    summary="The payment links of an invoice you can see, newest first",
    responses=problem_responses(404),
)
def list_links(principal: Reader, session: Db, invoice_id: uuid.UUID) -> PaymentLinkList:
    return PaymentLinkList(items=service.list_links(session, principal, invoice_id, customer=False))


# --- customer portal ----------------------------------------------------------------------

portal_router = APIRouter(
    prefix="/portal/payment-links", tags=["portal"], responses=problem_responses(401, 403)
)
Customer = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_INVOICE_READ))]


@portal_router.get(
    "",
    summary="The open payment link of one of my invoices (empty if there is none)",
    responses=problem_responses(404),
)
def my_link(principal: Customer, session: Db, invoice_id: uuid.UUID) -> PaymentLinkList:
    return PaymentLinkList(items=service.list_links(session, principal, invoice_id, customer=True))


# --- the webhook (no sign-in: Razorpay signs the body instead) ------------------------------

webhook_router = APIRouter(prefix="/integrations/razorpay", tags=["integrations"])


class WebhookAck(BaseModel):
    result: str


class BodyTooLargeError(DomainError):
    status_code = 413
    code = "body_too_large"

    def __init__(self) -> None:
        super().__init__("The request body is too large.")


@webhook_router.post(
    "/webhook",
    summary="Razorpay's payment link events (signed; only for Razorpay)",
    description="The signature is checked over the raw body before anything is read from it. "
    "Answers 200 for every verified delivery, also for events the CRM does not act on, so "
    "Razorpay does not keep resending them.",
    responses=problem_responses(401, 413),
)
async def razorpay_webhook(request: Request, session: Db) -> WebhookAck:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > service.MAX_BODY_BYTES:
        raise BodyTooLargeError()
    body = await request.body()
    if len(body) > service.MAX_BODY_BYTES:
        raise BodyTooLargeError()
    settings = _settings(request)
    signature = request.headers.get("x-razorpay-signature")
    event_id = request.headers.get("x-razorpay-event-id")

    def work() -> str:
        result = service.receive_webhook(session, settings, body, signature, event_id)
        session.commit()
        return result

    return WebhookAck(result=await run_in_threadpool(work))
