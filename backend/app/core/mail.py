"""Outgoing e-mail over SMTP (ADR 0005). Locally Mailpit catches every message.

``Mailer`` is a Protocol: the worker uses ``SmtpMailer``, tests use ``MemoryMailer``. E-mails
are sent only from background jobs (the worker), never inside an HTTP request, so a slow or
unreachable mail server can't make the CRM hang.

Two kinds of failure, because the worker treats them differently:
- ``MailUnavailableError``: the server could not be reached or answered "try later" → retry.
- ``MailRejectedError``: the server refused the message or recipient → retrying won't help.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)


class MailUnavailableError(Exception):
    """Temporary: try again later."""


class MailRejectedError(Exception):
    """Permanent: the message or a recipient was refused."""


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str  # e.g. "application/pdf"
    data: bytes


@dataclass(frozen=True)
class Mail:
    to: tuple[str, ...]
    subject: str
    text: str
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)
    reply_to: str | None = None


def build_message(mail: Mail, sender: str) -> EmailMessage:
    """Builds the MIME message. EmailMessage refuses line breaks in headers, which blocks
    header injection through names, subjects or addresses."""
    if not mail.to:
        raise MailRejectedError("no recipient")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(mail.to)
    message["Subject"] = mail.subject
    message["Message-ID"] = make_msgid(domain="crm.localhost")
    if mail.reply_to:
        message["Reply-To"] = mail.reply_to
    message.set_content(mail.text)
    for item in mail.attachments:
        maintype, _, subtype = item.content_type.partition("/")
        message.add_attachment(
            item.data, maintype=maintype, subtype=subtype, filename=item.filename
        )
    return message


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, mail: Mail) -> None:
        s = self._settings
        try:
            message = build_message(mail, s.mail_from)
        except ValueError as exc:  # e.g. a line break in a header
            raise MailRejectedError("invalid message header") from exc
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
                if s.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if s.smtp_username and s.smtp_password:
                    smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
                smtp.send_message(message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            raise MailRejectedError("recipient or sender refused") from exc
        except smtplib.SMTPResponseException as exc:
            # 5xx = permanent, 4xx = temporary (SMTP convention).
            if 500 <= exc.smtp_code < 600:
                raise MailRejectedError(f"SMTP {exc.smtp_code}") from exc
            raise MailUnavailableError(f"SMTP {exc.smtp_code}") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise MailUnavailableError(type(exc).__name__) from exc
        # Recipients are personal data: log only how many there were.
        logger.info("e-mail sent", extra={"recipients": len(mail.to)})


class MemoryMailer:
    """Collects messages instead of sending them (tests)."""

    def __init__(self) -> None:
        self.sent: list[Mail] = []
        self.fail_with: Exception | None = None

    def send(self, mail: Mail) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        build_message(mail, "test@crm.localhost")  # same header checks as SmtpMailer
        self.sent.append(mail)


def build_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(settings)
