"""Business rules of the Communication Center that need no database (ADR 0012)."""

import re

# The same coarse shape the database checks (ck_email_messages_address_shape): checking it here
# turns a strange address on a lead into a clear message instead of a database error.
_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+$")

# What the sender is told when an e-mail finally could not be sent. The outbox keeps only the
# error's type (or our own PermanentJobError text), never the mail server's answer, which may
# contain an address - so these codes are safe to store and show.
FAILURE_CODES = {
    "MailRejectedError": "recipient_refused",
    "MailUnavailableError": "mail_server_unavailable",
    "PermanentJobError: consent_withdrawn": "consent_withdrawn",
    "PermanentJobError: recipient_gone": "recipient_gone",
}
DEFAULT_FAILURE = "send_failed"


def looks_like_address(value: str | None) -> bool:
    return value is not None and len(value) <= 320 and _ADDRESS.match(value) is not None


def limit_reached(sent_in_last_hour: int, limit: int) -> bool:
    """True if one more e-mail would go over the person's hourly limit."""
    return sent_in_last_hour >= limit


def failure_code(error: str) -> str:
    return FAILURE_CODES.get(error, DEFAULT_FAILURE)
