"""Rules of the public website chat that need no database (ADR 0013)."""

import hashlib
import hmac
import re
import secrets
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

# The model gets this many tool rounds per visitor message, then must answer in words.
MAX_TOOL_ROUNDS = 2
# How much of the conversation the model sees each time.
HISTORY_MESSAGES = 20
# What the visitor sees if the model ends without a usable answer.
RESTING_REPLY = (
    "Our chat assistant is resting right now. Please leave a message through our contact form "
    "or call us, and an advisor will get back to you."
)
# Spoken when the receptionist is switched off, over budget or out of minutes. The page also offers
# the typed form, so the visitor is never left without a way to reach the team (ADR 0038).
VOICE_RESTING_REPLY = (
    "Our voice assistant is resting right now. Please type your name and phone number in the "
    "chat, or call us, and an advisor will get back to you."
)
VOICE_NO_SECRETS_REPLY = (
    "Please do not say card numbers, bank details, ID numbers or one-time passwords on this "
    "call. Tell me your name and phone number instead."
)
FALLBACK_REPLY = (
    "Sorry, I couldn't answer that. Please leave your name and phone number and an advisor will "
    "call you."
)
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,100}$")

SYSTEM_PROMPT = """You are the property concierge on the website of {organisation}.
Help home buyers by collecting, in a friendly and brief way: their full name, phone number,
the property type (apartment, villa, plot or commercial), their budget, and the area they want.
Ask for missing details one or two at a time. Convert budgets to whole rupees
(1 crore = 10000000, 1 lakh = 100000). Never invent prices, projects or availability.
When the visitor has confirmed their name and phone number, call the save_lead tool once.
Afterwards thank them and say an advisor will call. You can't look anything up in the CRM.
Answer in plain text only - no links, no images, no Markdown.
{language_rule}"""

# What the visitor chose on the page (ADR 0027). Fixed texts: nothing the visitor or a model typed
# is ever put into the prompt here.
LANGUAGE_RULES = {
    "en": "Answer the visitor in English.",
    "hi": (
        "Answer the visitor in Hindi, written in Devanagari script (even when they type Hindi in "
        "Latin letters). Write the notes you give to save_lead in English; keep the visitor's own "
        "words only for names and places."
    ),
    "te": (
        "Answer the visitor in Telugu, written in Telugu script (even when they type Telugu in "
        "Latin letters). Write the notes you give to save_lead in English; keep the visitor's "
        "own words only for names and places."
    ),
}

# Added to the prompt when the visitor is TALKING (ADR 0038). Fixed text; nothing the visitor or a
# model typed is put into it. The confirmation rule exists because speech recognition mishears
# names and places: the visitor must hear their phone number and name read back first.
VOICE_RULES = """This is a spoken conversation: the visitor hears your answer read aloud.
Start by saying that you are an automated assistant of {organisation}. Never claim to be a
person; if asked, say you are an automated assistant. Use at most two short sentences per turn,
no lists, no symbols, no emoji. Read the phone number back digit by digit and the name back, and
ask the visitor to confirm both BEFORE you call save_lead. If the visitor corrects you, read it
back again. Never ask for or accept card numbers, bank details, one-time passwords or ID numbers;
if the visitor starts saying one, tell them not to and move on."""

# Spoken numbers (ADR 0038, VR9): a speech recogniser may write "four one one one..." as words
# instead of digits, and the digit-based card check would not see it.
DIGIT_WORDS = {
    # English
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # Hindi (Devanagari)
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पाँच": "5", "पांच": "5",
    "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9",
    # Telugu
    "సున్నా": "0", "సున": "0", "ఒకటి": "1", "రెండు": "2", "మూడు": "3", "నాలుగు": "4",
    "ఐదు": "5", "ఆరు": "6", "ఏడు": "7", "ఎనిమిది": "8", "తొమ్మిది": "9",
}  # fmt: skip
# Words that announce a secret the receptionist must never take, in the three languages.
_SECRET_WORDS = ("otp", "cvv", "ओटीपी", "ఓటీపీ", "ఒటిపి")
# A phone number is 10 digits (12 with +91); a payment card is 13 to 19. Refuse from 13.
SPOKEN_CARD_MIN_DIGITS = 13


def spoken_number_refusal(text: str) -> bool:
    """True when ``text`` reads like a card number said aloud (13 or more digits in a row, as
    digit words in English, Hindi or Telugu mixed with digits) or names a one-time password or
    card security code. A normal phone number said aloud passes."""
    lowered = text.casefold()
    if any(word in lowered for word in _SECRET_WORDS):
        return True
    run = 0
    for raw in re.split(r"[\s,.;:-]+", lowered):
        token = raw.strip()
        if not token:
            continue
        if token in DIGIT_WORDS:
            run += 1
        elif token.isdigit():
            run += len(token)
        else:
            run = 0
        if run >= SPOKEN_CARD_MIN_DIGITS:
            return True
    return False


# Cleaning that does not make a name suspicious (a link or an image in a name does).
HARMLESS_NAME_FINDINGS = {"hidden_characters", "control_characters", "repeated_text"}

_PHONE = r"^\+?[0-9][0-9\s-]{6,18}[0-9]$"


def ascii_digits(text: str) -> str:
    """Devanagari, Telugu and other decimal digits as 0-9, so a phone number a visitor spoke or
    typed in their own script passes the same check as one written with 0-9 (ADR 0027)."""
    return "".join(str(unicodedata.digit(ch)) if ch.isdecimal() else ch for ch in text)


class SaveLeadArgs(BaseModel):
    """What the model may send to save_lead. Anything else is refused (extra="forbid")."""

    model_config = ConfigDict(extra="forbid")

    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
    ]
    phone: Annotated[
        str, BeforeValidator(ascii_digits), StringConstraints(strip_whitespace=True, pattern=_PHONE)
    ]
    email: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, max_length=320, pattern=r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$"
            ),
        ]
        | None
    ) = None
    property_type: Literal["apartment", "villa", "plot", "commercial"] | None = None
    budget_min_inr: Annotated[int, Field(ge=0, le=1_000_000_000_000)] | None = None
    budget_max_inr: Annotated[int, Field(ge=0, le=1_000_000_000_000)] | None = None
    location: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
        | None
    ) = None
    notes: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
        | None
    ) = None

    @model_validator(mode="after")
    def _budget_in_order(self) -> "SaveLeadArgs":
        low, high = self.budget_min_inr, self.budget_max_inr
        if low is not None and high is not None and low > high:
            raise ValueError("budget_min_inr can't be above budget_max_inr")
        return self


def _tool_definition() -> dict[str, Any]:
    """The save_lead tool, built from SaveLeadArgs so the two can never drift apart."""
    schema = SaveLeadArgs.model_json_schema()
    return {
        "name": "save_lead",
        "description": (
            "Save the visitor's confirmed details as a lead for the sales team. Call it once, "
            "after the visitor confirmed at least their full name and phone number. Budgets are "
            "whole rupees."
        ),
        "input_schema": {
            "type": "object",
            "properties": schema["properties"],
            "required": ["full_name", "phone"],
            "additionalProperties": False,
        },
    }


SAVE_LEAD_TOOL = _tool_definition()


def split_name(full_name: str) -> tuple[str | None, str]:
    """ "Anil Kumar Reddy" -> ("Anil Kumar", "Reddy"); a single word is the last name."""
    parts = full_name.split()
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


def new_token() -> str:
    """A random conversation token (256 bits); only its hash is ever stored."""
    return secrets.token_urlsafe(32) + secrets.token_urlsafe(8)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(address: str, server_key: str) -> str:
    """A keyed hash of the visitor's address: enough to count, impossible to read back."""
    return hmac.new(server_key.encode(), address.encode(), hashlib.sha256).hexdigest()
