"""Guardrails for the customer portal assistant (input and output).

Input is checked before any model call; output is checked before it is stored or returned.
These are deterministic, explainable rules, not a replacement for the model's own refusal.
"""

import re
from dataclasses import dataclass

from app.core.screening import screen

MAX_INPUT_CHARS = 2000
MAX_OUTPUT_CHARS = 8000

INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "system prompt",
    "developer message",
    "jailbreak",
    "you are now",
    "act as the system",
    "reveal your instructions",
    "print your instructions",
    "show your instructions",
)

PII_PATTERNS = (
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),  # payment-card-like digit runs
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),  # API key
)

SECRET_PATTERNS = (
    "system prompt",
    "developer message",
    "ignore previous",
    "ignore all previous",
    "sk-",
    "akia",
    "postgres://",
    "postgresql://",
    "password=",
    "127.0.0.1",
    "localhost:",
)

SAFE_OUTPUT = "I can't share that here. Please contact our support team and a person will help you."


@dataclass(frozen=True)
class InputDecision:
    allowed: bool
    reason: str = ""
    # What to use instead of the typed text: hidden characters, markup, images and floods taken
    # out (ADR 0017). Empty when the text is refused.
    clean: str = ""


def inspect_input(text: str) -> InputDecision:
    """Reject prompt injection, obvious secrets and over-long questions; clean the rest.

    What a person types keeps its links and e-mail addresses. Hidden characters, markup,
    images and floods are taken out (``decision.clean`` is what to use from here on), and an
    instruction hidden in them - split by invisible characters, or spelled in invisible "tag"
    characters - is refused like one typed openly."""
    if len(" ".join(text.split())) > MAX_INPUT_CHARS:
        return InputDecision(False, "Please shorten your question.")
    screened = screen(text, strip_links=False, strip_addresses=False)
    cleaned = screened.clean
    flat = " ".join(cleaned.split())
    if not flat:
        return InputDecision(False, "Please type a question.")
    lowered = flat.lower()
    if any(f.code == "instruction_phrase" for f in screened.findings) or any(
        pattern in lowered for pattern in INJECTION_PATTERNS
    ):
        return InputDecision(False, "I can only help with your account and support questions.")
    if any(pattern.search(flat) for pattern in PII_PATTERNS):
        return InputDecision(
            False,
            "Please don't share card numbers, national IDs or API keys in chat.",
        )
    return InputDecision(True, clean=cleaned)


def sanitise_output(text: str) -> str:
    """Return an answer safe to show a customer; never leak prompts, keys or internal hosts."""
    cleaned = (text or "").strip()[:MAX_OUTPUT_CHARS]
    if not cleaned:
        return SAFE_OUTPUT
    if any(marker in cleaned.lower() for marker in SECRET_PATTERNS):
        return SAFE_OUTPUT
    # A model that read a poisoned record could write an image or a link whose address carries
    # data out when the page loads or is clicked (ADR 0018). Links to other sites and images are
    # removed (the words stay, a marker shows something was there); links inside the CRM stay.
    cleaned = screen(cleaned, strip_links=True, strip_addresses=False).clean.strip()
    if not cleaned or any(marker in cleaned.lower() for marker in SECRET_PATTERNS):
        return SAFE_OUTPUT
    return cleaned
