"""Communication Center: sending one-to-one e-mails (ADR 0012, step CC2).

    request ──► checks ──► message "queued" + outbox job + timeline entry + audit  (one commit)
    worker  ──► mailer ──► "sent"  |  retries used up / refused ──► "failed" + event → notification

Services never commit; the router commits once. The worker's job runs in the worker's own
transaction (app/core/outbox.py).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish
from app.core.mail import Mail, Mailer
from app.core.outbox import PermanentJobError, enqueue
from app.core.records import Recipient
from app.modules.accounts import api as accounts_api
from app.modules.activities import api as activities_api
from app.modules.communications import repository, rules
from app.modules.communications.models import EmailMessage
from app.modules.communications.schemas import EmailSend
from app.modules.contacts import api as contacts_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.sales import api as sales_api

EMAIL_JOB = "communication.email"
FAILED_EVENT = "communication.email_failed"


class RecipientNotFoundError(NotFoundError):
    code = "recipient_not_found"

    def __init__(self) -> None:
        super().__init__("Lead or contact not found.")


class RelatedNotFoundError(NotFoundError):
    code = "related_not_found"

    def __init__(self) -> None:
        super().__init__("Account or deal not found.")


class TemplateNotFoundError(NotFoundError):
    code = "template_not_found"

    def __init__(self) -> None:
        super().__init__("Template not found.")


class MessageNotFoundError(NotFoundError):
    code = "message_not_found"

    def __init__(self) -> None:
        super().__init__("E-mail not found.")


class RelatedMismatchError(DomainError):
    status_code = 422
    code = "related_record_mismatch"

    def __init__(self) -> None:
        super().__init__("The account or deal must belong to the contact's account.")


class NoEmailAddressError(ConflictError):
    code = "recipient_has_no_email"

    def __init__(self) -> None:
        super().__init__("This lead or contact has no usable e-mail address. Add one first.")


class ConsentWithdrawnError(ConflictError):
    code = "consent_withdrawn"

    def __init__(self) -> None:
        super().__init__("This contact asked not to receive e-mails.")


class SendLimitError(DomainError):
    status_code = 429
    code = "send_limit_reached"

    def __init__(self, limit: int) -> None:
        super().__init__(f"You have sent {limit} e-mails in the last hour. Try again later.")


def _sender(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.COMMUNICATION_SEND)
    ):
        raise ForbiddenError("You may not send e-mails.")
    return principal.tenant_id, principal.user_id


def _recipient(session: Session, principal: Principal, data: EmailSend) -> Recipient:
    found = None
    if data.lead_id is not None:
        found = leads_api.lead_recipient(session, principal, data.lead_id)
    elif data.contact_id is not None:
        found = contacts_api.contact_recipient(session, principal, data.contact_id)
    if found is None:
        raise RecipientNotFoundError()
    return found


def _check_related(
    session: Session, principal: Principal, data: EmailSend, recipient: Recipient
) -> None:
    """The account or deal must be visible to the sender AND be the contact's own."""
    if data.account_id is not None:
        if not accounts_api.is_readable_account(session, principal, data.account_id):
            raise RelatedNotFoundError()
        if data.account_id != recipient.account_id:
            raise RelatedMismatchError()
    if data.opportunity_id is not None:
        visible, account_id = sales_api.opportunity_account_id(
            session, principal, data.opportunity_id
        )
        if not visible:
            raise RelatedNotFoundError()
        if account_id != recipient.account_id:
            raise RelatedMismatchError()


def send_email(
    session: Session, principal: Principal, data: EmailSend, *, hourly_limit: int
) -> EmailMessage:
    """Queue an e-mail to a lead or contact the sender may read; the worker sends it."""
    tenant_id, user_id = _sender(principal)
    recipient = _recipient(session, principal, data)
    _check_related(session, principal, data, recipient)
    if data.template_id is not None and not repository.active_template_exists(
        session, tenant_id, data.template_id
    ):
        raise TemplateNotFoundError()
    address = recipient.email
    if address is None or not rules.looks_like_address(address):
        raise NoEmailAddressError()
    if recipient.consent_withdrawn:
        raise ConsentWithdrawnError()
    since = datetime.now(UTC) - timedelta(hours=1)
    if rules.limit_reached(repository.sent_since(session, tenant_id, user_id, since), hourly_limit):
        raise SendLimitError(hourly_limit)

    message = EmailMessage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        direction="outbound",
        status="queued",
        lead_id=data.lead_id,
        contact_id=data.contact_id,
        account_id=data.account_id,
        opportunity_id=data.opportunity_id,
        to_address=address,
        subject=data.subject,
        body=data.body,
        template_id=data.template_id,
        sent_by_user_id=user_id,
    )
    session.add(message)
    session.flush()
    enqueue(session, tenant_id=tenant_id, kind=EMAIL_JOB, payload={"message_id": str(message.id)})
    activities_api.log_email(
        session, principal, subject=data.subject, lead_id=data.lead_id, contact_id=data.contact_id
    )
    # Who and which record, never the address or the text (personal data stays in its row).
    record_audit(
        session,
        principal,
        action="email.queued",
        entity_type="email_message",
        entity_id=message.id,
        changes={
            "recipient_type": "lead" if data.lead_id else "contact",
            "recipient_id": str(data.lead_id or data.contact_id),
            "template_id": str(data.template_id) if data.template_id else None,
        },
    )
    return message


def get_message(session: Session, principal: Principal, message_id: uuid.UUID) -> EmailMessage:
    message = repository.get_readable_message(session, principal, message_id)
    if message is None:
        raise MessageNotFoundError()
    return message


def message_brief(
    session: Session, principal: Principal, message_id: uuid.UUID
) -> tuple[str, str] | None:
    """(subject, page of the recipient) for a message this principal may see, else None."""
    message = repository.get_readable_message(session, principal, message_id)
    if message is None:
        return None
    link = f"/leads/{message.lead_id}" if message.lead_id else f"/contacts/{message.contact_id}"
    return message.subject, link


# --- worker ---------------------------------------------------------------------------------


def run_send_job(
    session: Session, mailer: Mailer, *, tenant_id: uuid.UUID, message_id: uuid.UUID
) -> None:
    """Send one queued e-mail. Safe to run twice: only a "queued" message is sent."""
    message = repository.get_message_for_update(session, tenant_id, message_id)
    if message is None or message.status != "queued":
        return
    # Consent may have been withdrawn after the e-mail was queued.
    if message.contact_id is not None and contacts_api.email_consent_withdrawn(
        session, tenant_id, message.contact_id
    ):
        raise PermanentJobError("consent_withdrawn")
    mailer.send(
        Mail(
            to=(message.to_address,),
            subject=message.subject,
            text=message.body,
            reply_to=identity_api.staff_email(session, tenant_id, message.sent_by_user_id),
        )
    )
    message.status = "sent"
    message.sent_at = datetime.now(UTC)


def send_failed(session: Session, tenant_id: uuid.UUID, message_id: uuid.UUID, error: str) -> None:
    """The job gave up: mark the message failed and tell the sender (via an event)."""
    message = repository.get_message_for_update(session, tenant_id, message_id)
    if message is None or message.status != "queued":
        return
    message.status = "failed"
    message.error_code = rules.failure_code(error)
    publish(
        session,
        tenant_id,
        FAILED_EVENT,
        {"message_id": str(message.id), "sender_id": str(message.sent_by_user_id)},
    )
