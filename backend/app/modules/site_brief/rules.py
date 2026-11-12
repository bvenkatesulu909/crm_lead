"""Pure rules of the rep's brief before a site visit (ADR 0029): no database, no model, no network.

The brief is built by code from what the CRM already holds. Every line is a fact, an assumption, a
gap (turned into a question) or a note, and keeps its source; nothing is invented and no model reads
anything. This module only arranges the inputs the service gathered.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.core.screening import screen
from app.modules.assistant import api as assistant_api

PLACE_MAX = 100
EXCERPT_MAX = 160
RECENT_ENTRIES = 5

# One plain question for every one of the twelve buyer memory keys (ADR 0028).
QUESTIONS: dict[str, str] = {
    "budget": "What budget are you comfortable with?",
    "property_type": (
        "What kind of home are you looking for - apartment, villa, plot or commercial?"
    ),
    "location": "Which areas are you considering?",
    "timeline": "When would you like to move in or to buy?",
    "purpose": "Is this for you to live in, or an investment?",
    "financing": "How are you planning to pay - a loan, savings, or both?",
    "household": "Who will be living in the home?",
    "decision_makers": "Who else will be part of the decision?",
    "must_haves": "What must the home have?",
    "deal_breakers": "Is there anything that would rule a home out?",
    "current_home": "Where do you live now - do you rent, own, or are you selling?",
    "other_options": "Which other projects have you seen or are you considering?",
}

LANGUAGE_NAMES = {"hi": "Hindi", "te": "Telugu", "en": "English"}


class PlaceError(ValueError):
    """The place typed for this view was refused (too long, a card number, an instruction)."""


def clean_place(raw: str | None) -> str | None:
    """The place for this one view: short, plain, never stored. None when nothing was typed."""
    if raw is None or not raw.strip():
        return None
    decision = assistant_api.inspect_input(raw)
    if not decision.allowed:
        raise PlaceError(f"The place was refused: {decision.reason}")
    cleaned = screen(decision.clean, strip_links=True, strip_addresses=False).clean
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    if len(cleaned) > PLACE_MAX:
        raise PlaceError(f"The place is too long (at most {PLACE_MAX} characters).")
    return cleaned


def excerpt(text: str | None) -> str:
    """The first words of a timeline note as plain text: links, images, markup and hidden
    characters out, cut at 160 characters (marked with an ellipsis when cut)."""
    if not text:
        return ""
    cleaned = screen(text, strip_links=True, strip_addresses=False).clean
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= EXCERPT_MAX:
        return cleaned
    return cleaned[:EXCERPT_MAX].rstrip() + "…"


# --- the inputs the service gathers --------------------------------------------------------------


@dataclass(frozen=True)
class KnownFact:
    key: str
    label: str
    value: str
    source: str | None
    quote: str | None
    recorded_on: datetime


@dataclass(frozen=True)
class KnownGuess:
    key: str
    label: str
    value: str
    reason: str | None
    recorded_on: datetime


@dataclass(frozen=True)
class BuyerFacts:
    name: str
    status: str
    source: str | None
    owner_name: str | None
    phone: str | None
    email: str | None
    language: str | None
    # What the lead form says (already written as people say it); None when empty.
    form_budget: str | None
    form_property_type: str | None
    form_location: str | None


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    occurred_at: datetime
    subject: str
    excerpt: str


@dataclass(frozen=True)
class OpenTask:
    subject: str
    due_at: datetime | None
    priority: str


# --- the brief -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ask:
    kind: str  # "confirm" (an assumption to check) or "gap" (something not known yet)
    key: str
    label: str
    text: str


@dataclass(frozen=True)
class Caution:
    code: str
    text: str


@dataclass(frozen=True)
class TaskLine:
    subject: str
    due_at: datetime | None
    priority: str
    overdue: bool


@dataclass(frozen=True)
class Brief:
    as_of: datetime
    place: str | None
    buyer: BuyerFacts
    facts: list[KnownFact]
    guesses: list[KnownGuess]
    ask: list[Ask]
    recent: list[TimelineEntry]
    tasks: list[TaskLine]
    cautions: list[Caution]


def _task_lines(tasks: Sequence[OpenTask], now: datetime) -> list[TaskLine]:
    lines = [
        TaskLine(t.subject, t.due_at, t.priority, t.due_at is not None and t.due_at < now)
        for t in tasks
    ]
    # Overdue first (oldest first), then the dated ones by date, then the undated.
    far = datetime.max.replace(tzinfo=now.tzinfo)
    return sorted(lines, key=lambda t: (not t.overdue, t.due_at is None, t.due_at or far))


def _cautions(
    buyer: BuyerFacts,
    facts: Sequence[KnownFact],
    guesses: Sequence[KnownGuess],
    tasks: Sequence[TaskLine],
) -> list[Caution]:
    found: list[Caution] = []
    if buyer.status == "converted":
        found.append(Caution("lead_converted", "This lead is already converted to a customer."))
    if buyer.status == "unqualified":
        found.append(Caution("lead_unqualified", "This lead was marked unqualified."))
    if not buyer.phone and not buyer.email:
        found.append(
            Caution(
                "no_contact_details", "There is no phone number and no e-mail address on the lead."
            )
        )
    if buyer.language in ("hi", "te"):
        name = LANGUAGE_NAMES[buyer.language]
        found.append(
            Caution(
                "speaks_other_language", f"The buyer prefers {name} - speak (and call) in {name}."
            )
        )
    if len(guesses) > len(facts):
        found.append(
            Caution(
                "more_guesses_than_facts",
                f"{len(guesses)} assumptions and only {len(facts)} facts - confirm what you can "
                "early in the visit.",
            )
        )
    held = {f.key for f in facts} | {g.key for g in guesses}
    missing = [
        text
        for key, value, text in (
            ("budget", buyer.form_budget, "a budget"),
            ("property_type", buyer.form_property_type, "a property type"),
            ("location", buyer.form_location, "an area"),
        )
        if value and key not in held
    ]
    if missing:
        found.append(
            Caution(
                "form_not_in_memory",
                f"The lead form has {' and '.join(missing)} that buyer memory does not hold yet - "
                "use 'Copy from the lead form'.",
            )
        )
    overdue = sum(1 for t in tasks if t.overdue)
    if overdue:
        found.append(
            Caution("overdue_follow_ups", f"{overdue} follow-up(s) for this lead are overdue.")
        )
    return found


def build_brief(
    *,
    buyer: BuyerFacts,
    facts: Sequence[KnownFact],
    guesses: Sequence[KnownGuess],
    recent: Sequence[TimelineEntry],
    tasks: Sequence[OpenTask],
    place: str | None,
    now: datetime,
    keys: Sequence[tuple[str, str]] | None = None,
) -> Brief:
    """Arrange the gathered facts into the six sections. ``keys`` is the ordered (key, label) list
    of buyer memory; it defaults to the questions' own order."""
    ordered = (
        list(keys) if keys is not None else [(k, k.replace("_", " ").title()) for k in QUESTIONS]
    )
    held = {f.key for f in facts} | {g.key for g in guesses}
    ask = [Ask("confirm", g.key, g.label, f"Confirm: {g.label} - {g.value}") for g in guesses]
    ask += [Ask("gap", key, label, QUESTIONS[key]) for key, label in ordered if key not in held]
    lines = _task_lines(tasks, now)
    return Brief(
        as_of=now,
        place=place,
        buyer=buyer,
        facts=list(facts),
        guesses=list(guesses),
        ask=ask,
        recent=list(recent)[:RECENT_ENTRIES],
        tasks=lines,
        cautions=_cautions(buyer, facts, guesses, lines),
    )
