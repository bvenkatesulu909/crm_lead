"""Business rules of the Communication Center that need no database (ADR 0012)."""

import re
from collections.abc import Mapping

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


# Template placeholders (ADR 0012): a fixed list, filled by plain text replacement. There is no
# template engine and no expressions, so a template can never run code or reach other data.
PLACEHOLDERS: dict[str, str] = {
    "recipient.first_name": "First name of the lead or contact",
    "recipient.full_name": "First and last name of the lead or contact",
    "recipient.company": "The lead's company, or the contact's account",
    "sender.name": "Your name",
    "sender.email": "Your e-mail address",
    "organisation.name": "The name of your organisation",
}
# Sample values for a preview without a recipient (shown to the template's author).
SAMPLE_RECIPIENT = {
    "recipient.first_name": "Ada",
    "recipient.full_name": "Ada Lovelace",
    "recipient.company": "Example Ltd",
}
_TOKEN = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


def placeholder_problems(text: str) -> list[str]:
    """Unknown placeholders (as ``{{name}}``) and unbalanced braces, each once, in order."""
    problems: list[str] = []
    for match in _TOKEN.finditer(text):
        name = match.group(1)
        if name not in PLACEHOLDERS:
            problems.append(f"{{{{{name}}}}}")
    rest = _TOKEN.sub("\x00", text)
    if "{{" in rest:
        problems.append("'{{' without '}}'")
    if "}}" in rest:
        problems.append("'}}' without '{{'")
    return list(dict.fromkeys(problems))


def render(
    text: str, values: Mapping[str, str | None], *, single_line: bool = False
) -> tuple[str, list[str]]:
    """Fill the placeholders in ONE pass (a value is never expanded again). Returns the text
    and the placeholders that had no value. ``single_line`` keeps line breaks out of a
    subject, so a name can't add mail headers."""
    missing: list[str] = []

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        value = values.get(name)
        if not value:
            missing.append(name)
            return ""
        return " ".join(value.split()) if single_line else value

    return _TOKEN.sub(fill, text), list(dict.fromkeys(missing))


def looks_like_address(value: str | None) -> bool:
    return value is not None and len(value) <= 320 and _ADDRESS.match(value) is not None


def limit_reached(sent_in_last_hour: int, limit: int) -> bool:
    """True if one more e-mail would go over the person's hourly limit."""
    return sent_in_last_hour >= limit


def failure_code(error: str) -> str:
    return FAILURE_CODES.get(error, DEFAULT_FAILURE)
