"""Communication Center: one-to-one e-mails (step CC2) and templates (step CC3), ADR 0012.

    request ──► checks ──► message "queued" + outbox job + timeline entry + audit  (one commit)
    worker  ──► mailer ──► "sent"  |  retries used up / refused ──► "failed" + event → notification

Services never commit; the router commits once. The worker's job runs in the worker's own
transaction (app/core/outbox.py).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import diff, record_audit
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
from app.modules.communications.models import EmailMessage, EmailTemplate
from app.modules.communications.schemas import (
    EmailLogReceived,
    EmailSend,
    PlaceholderRead,
    TemplateCreate,
    TemplatePreview,
    TemplatePreviewRequest,
    TemplateUpdate,
)
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


class TemplateNameTakenError(ConflictError):
    code = "template_name_taken"

    def __init__(self) -> None:
        super().__init__("Another template already has this name.")


class PlaceholderError(DomainError):
    status_code = 422
    code = "unknown_placeholder"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("Unknown or broken placeholders: " + ", ".join(problems) + ".")


class VersionConflictError(ConflictError):
    code = "version_conflict"

    def __init__(self) -> None:
        super().__init__("The template was changed by someone else. Reload it.")


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


def _recipient(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
) -> Recipient:
    """The lead or contact, loaded under ITS module's read rules (not visible: 404)."""
    found = None
    if lead_id is not None:
        found = leads_api.lead_recipient(session, principal, lead_id)
    elif contact_id is not None:
        found = contacts_api.contact_recipient(session, principal, contact_id)
    if found is None:
        raise RecipientNotFoundError()
    return found


def _check_related(
    session: Session,
    principal: Principal,
    data: EmailSend | EmailLogReceived,
    recipient: Recipient,
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
    recipient = _recipient(session, principal, data.lead_id, data.contact_id)
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


# --- templates (step CC3) ------------------------------------------------------------------


def _template_manager(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.COMMUNICATION_TEMPLATE_MANAGE)
    ):
        raise ForbiddenError("You may not manage e-mail templates.")
    return principal.tenant_id, principal.user_id


def _check_placeholders(*texts: str) -> None:
    problems: list[str] = []
    for text in texts:
        problems += rules.placeholder_problems(text)
    if problems:
        raise PlaceholderError(list(dict.fromkeys(problems)))


def _flush_template(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError() from exc
    except IntegrityError as exc:  # two managers saving the same name at the same moment
        raise TemplateNameTakenError() from exc


def placeholders() -> list[PlaceholderRead]:
    return [PlaceholderRead(name=n, description=d) for n, d in rules.PLACEHOLDERS.items()]


def list_templates(
    session: Session, principal: Principal, *, include_inactive: bool
) -> Sequence[EmailTemplate]:
    """Active templates; managers may ask for deactivated ones too (others never see them)."""
    return repository.list_templates(session, principal, include_inactive=include_inactive)


def get_template(session: Session, principal: Principal, template_id: uuid.UUID) -> EmailTemplate:
    template = repository.get_readable_template(session, principal, template_id)
    if template is None:
        raise TemplateNotFoundError()
    return template


def create_template(session: Session, principal: Principal, data: TemplateCreate) -> EmailTemplate:
    tenant_id, user_id = _template_manager(principal)
    _check_placeholders(data.subject, data.body)
    if repository.template_name_taken(session, tenant_id, data.name, None):
        raise TemplateNameTakenError()
    template = EmailTemplate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=data.name,
        subject=data.subject,
        body=data.body,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    session.add(template)
    _flush_template(session)
    record_audit(
        session,
        principal,
        action="template.created",
        entity_type="email_template",
        entity_id=template.id,
        changes={"name": template.name},
    )
    session.refresh(template)
    return template


def update_template(
    session: Session, principal: Principal, template_id: uuid.UUID, data: TemplateUpdate
) -> EmailTemplate:
    """Rename, rewrite, deactivate or reactivate a template (optimistic locking by version)."""
    tenant_id, user_id = _template_manager(principal)
    template = get_template(session, principal, template_id)
    if template.version != data.version:
        raise VersionConflictError()
    changes = data.changes()
    _check_placeholders(
        str(changes.get("subject", template.subject)), str(changes.get("body", template.body))
    )
    name = changes.get("name")
    if isinstance(name, str) and repository.template_name_taken(
        session, tenant_id, name, template.id
    ):
        raise TemplateNameTakenError()
    before = {"name": template.name, "is_active": template.is_active}
    texts_before = {"subject": template.subject, "body": template.body}
    for field, value in changes.items():
        setattr(template, field, value)
    template.updated_by_user_id = user_id
    # Name and status as old/new; for the texts only THAT they changed (they can be long).
    changed: dict[str, object] = dict(
        diff(before, {"name": template.name, "is_active": template.is_active})
    )
    for field, old in texts_before.items():
        if getattr(template, field) != old:
            changed[field] = {"changed": True}
    if changed:
        record_audit(
            session,
            principal,
            action="template.updated",
            entity_type="email_template",
            entity_id=template.id,
            changes=changed,
        )
    _flush_template(session)
    session.refresh(template)
    return template


def _organisation_name(session: Session, principal: Principal) -> str | None:
    if principal.tenant_name:
        return principal.tenant_name
    return identity_api.tenant_name(session, principal.tenant_id) if principal.tenant_id else None


def preview_template(
    session: Session,
    principal: Principal,
    template_id: uuid.UUID,
    data: TemplatePreviewRequest,
) -> TemplatePreview:
    """The template filled in for one lead or contact the user may read (or sample values)."""
    template = get_template(session, principal, template_id)
    values: dict[str, str | None] = {
        "sender.name": principal.display_name,
        "sender.email": principal.email,
        "organisation.name": _organisation_name(session, principal),
    }
    if data.lead_id is None and data.contact_id is None:
        values |= rules.SAMPLE_RECIPIENT
    else:
        recipient = _recipient(session, principal, data.lead_id, data.contact_id)
        company = recipient.company
        if company is None and recipient.account_id is not None and principal.tenant_id:
            company = accounts_api.account_name(session, principal.tenant_id, recipient.account_id)
        values |= {
            "recipient.first_name": recipient.first_name,
            "recipient.full_name": recipient.full_name,
            "recipient.company": company,
        }
    subject, missing_in_subject = rules.render(template.subject, values, single_line=True)
    body, missing_in_body = rules.render(template.body, values)
    return TemplatePreview(
        subject=subject,
        body=body,
        missing=list(dict.fromkeys(missing_in_subject + missing_in_body)),
    )


# --- history, list and logged e-mails (step CC4) ---------------------------------------------


class OneRecordError(DomainError):
    status_code = 422
    code = "one_record_required"

    def __init__(self) -> None:
        super().__init__("Ask for the history of exactly one lead, contact, account or deal.")


class RecordNotFoundError(NotFoundError):
    code = "record_not_found"

    def __init__(self) -> None:
        super().__init__("Record not found.")


_COMMUNICATION_PERMISSIONS = (
    Permission.COMMUNICATION_SEND,
    Permission.COMMUNICATION_READ_ALL,
    Permission.COMMUNICATION_READ_OWN,
)


def list_messages(
    session: Session, principal: Principal, filters: repository.MessageFilters
) -> tuple[Sequence[EmailMessage], int]:
    """The Communication Center: every e-mail (read:all) or the user's own (read:own)."""
    return repository.search_messages(session, principal, filters)


def record_history(
    session: Session,
    principal: Principal,
    *,
    lead_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[EmailMessage], int]:
    """All e-mails of ONE record, for anyone who may read that record (its module decides).

    An account's history also holds the e-mails to its contacts and those filed under its deals.
    """
    if (
        principal.tenant_id is None
        or principal.user_type != "staff"
        or not any(principal.has_permission(p) for p in _COMMUNICATION_PERMISSIONS)
    ):
        raise ForbiddenError("You may not read e-mails.")
    tenant_id = principal.tenant_id
    if sum(x is not None for x in (lead_id, contact_id, account_id, opportunity_id)) != 1:
        raise OneRecordError()
    belongs: ColumnElement[bool]
    if lead_id is not None:
        if not leads_api.is_readable_lead(session, principal, lead_id):
            raise RecordNotFoundError()
        belongs = EmailMessage.lead_id == lead_id
    elif contact_id is not None:
        if not contacts_api.is_readable_contact(session, principal, contact_id):
            raise RecordNotFoundError()
        belongs = EmailMessage.contact_id == contact_id
    elif opportunity_id is not None:
        if not sales_api.is_readable_opportunity(session, principal, opportunity_id):
            raise RecordNotFoundError()
        belongs = EmailMessage.opportunity_id == opportunity_id
    elif account_id is not None:
        if not accounts_api.is_readable_account(session, principal, account_id):
            raise RecordNotFoundError()
        contacts = contacts_api.contact_ids_by_account(session, tenant_id, [account_id])
        deals = sales_api.opportunity_ids_by_account(session, tenant_id, [account_id])
        belongs = or_(
            EmailMessage.account_id == account_id,
            EmailMessage.contact_id.in_(contacts[account_id]),
            EmailMessage.opportunity_id.in_(deals[account_id]),
        )
    else:  # unreachable: exactly one record was given (checked above)
        raise OneRecordError()
    return repository.record_history(session, tenant_id, belongs, limit=limit, offset=offset)


def log_received(session: Session, principal: Principal, data: EmailLogReceived) -> EmailMessage:
    """Store an e-mail the lead or contact sent us (pasted in by staff). Nothing is sent, so
    neither consent nor the sending limit apply; the record's read rules do."""
    tenant_id, user_id = _sender(principal)
    recipient = _recipient(session, principal, data.lead_id, data.contact_id)
    _check_related(session, principal, data, recipient)
    address = recipient.email
    if address is None or not rules.looks_like_address(address):
        raise NoEmailAddressError()
    message = EmailMessage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        direction="inbound_logged",
        status="logged",
        lead_id=data.lead_id,
        contact_id=data.contact_id,
        account_id=data.account_id,
        opportunity_id=data.opportunity_id,
        to_address=address,
        subject=data.subject,
        body=data.body,
        sent_by_user_id=user_id,
    )
    session.add(message)
    session.flush()
    activities_api.log_email(
        session,
        principal,
        subject=data.subject,
        lead_id=data.lead_id,
        contact_id=data.contact_id,
        received=True,
    )
    record_audit(
        session,
        principal,
        action="email.logged",
        entity_type="email_message",
        entity_id=message.id,
        changes={
            "recipient_type": "lead" if data.lead_id else "contact",
            "recipient_id": str(data.lead_id or data.contact_id),
        },
    )
    return message


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
