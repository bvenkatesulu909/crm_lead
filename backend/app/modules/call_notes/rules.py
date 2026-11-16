"""Pure rules of the call notes (ADR 0035, CN1): no database, no model, no network.

A model reads a call transcript and says, for each field of a sales checklist, whether the buyer
STATED the answer, whether it is only ASSUMED, or whether it is UNKNOWN. This file is the part that
does not trust the model: every quote it gives is looked up in the stored transcript, word for word
(only case, punctuation and spacing are ignored), and a line whose quote cannot be found becomes
"unknown" - an empty line, never a believable invented one. Numbers are kept exactly as said.
"""

import unicodedata
from dataclasses import dataclass, field

from app.core.screening import screen

FRAMEWORK_NAMES = ("bant", "meddic")
DEFAULT_FRAMEWORK = "bant"
STATES = ("stated", "assumed", "unknown")
NOTE = "note"  # the field name of a free "call note" line (always a stated line with a quote)

MAX_VALUE = 150
MAX_QUOTE = 300
MAX_REASON = 300
MAX_NOTE_TEXT = 200
MAX_NOTES = 8
MAX_PROPOSALS = 5  # buyer-memory proposals per run (ADR 0035 CN7); one follow-up task besides
MAX_TRANSCRIPT_CHARS = 60_000
MIN_QUOTE_CHARS = 4  # letters and digits a quote needs, or it would "prove" anything
MAX_WINDOW_MS = 120_000  # the time span a model may name for one quote
MAX_SPAN_MS = 300_000  # the longest stretch of a recording a single stored line may point at
TIME_SLACK_MS = 2_000  # how far a model's times may be off the segment that holds the words


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    hint: str  # what the model is told to look for
    memory_key: str | None  # the buyer-memory key a proposal would use; None = checklist only


FRAMEWORKS: dict[str, tuple[Field, ...]] = {
    "bant": (
        Field(
            "budget",
            "Budget",
            "How much the buyer says they can or want to spend, in their own words.",
            "budget",
        ),
        Field(
            "authority",
            "Authority",
            "Who decides or pays, and whether the person on the call is that person.",
            "decision_makers",
        ),
        Field(
            "need",
            "Need",
            "What the buyer needs: the kind of home, size, place and reasons they give.",
            "must_haves",
        ),
        Field(
            "timeline",
            "Timeline",
            "When the buyer says they want to decide, buy or move in.",
            "timeline",
        ),
    ),
    "meddic": (
        Field(
            "metrics",
            "Metrics",
            "Numbers the buyer says they will judge the purchase by (returns, yield, price).",
            None,
        ),
        Field(
            "economic_buyer",
            "Economic buyer",
            "The person who controls the money and has the final say, if the buyer names them.",
            "decision_makers",
        ),
        Field(
            "decision_criteria",
            "Decision criteria",
            "What the buyer says a home or project must have to be chosen.",
            "must_haves",
        ),
        Field(
            "decision_process",
            "Decision process",
            "The steps or people the buyer says a decision has to go through, and when.",
            None,
        ),
        Field(
            "identify_pain",
            "Identify pain",
            "The problem or reason that makes the buyer want to buy now, in their words.",
            "purpose",
        ),
        Field(
            "champion",
            "Champion",
            "Someone on the buyer's side who is pushing for this purchase, if the buyer says so.",
            None,
        ),
    ),
}
ALL_FIELDS: tuple[str, ...] = tuple(f.key for fields in FRAMEWORKS.values() for f in fields)


class AnswerRefused(ValueError):
    """The model's answer cannot be used at all. ``code`` is stable; the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Claim:
    """What the model says about one checklist field (before any check)."""

    field: str
    state: str
    value: str | None
    quote: str | None
    start_ms: int | None
    end_ms: int | None
    reason: str | None


@dataclass(frozen=True)
class NoteClaim:
    """One free call note the model wants to keep: a short sentence and the words behind it."""

    text: str
    quote: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Line:
    """One checked line, ready to store. ``note_code`` says why a claim was turned into unknown."""

    field: str
    state: str
    value: str | None
    quote: str | None
    start_ms: int | None
    end_ms: int | None
    reason: str | None
    note_code: str | None


@dataclass(frozen=True)
class Verified:
    lines: list[Line]  # the checklist in the frame's order, then the notes
    downgraded: int  # claims turned into unknown
    dropped_notes: int
    # Kinds of finding (links, instruction-like words...) in what the model wrote, never the text.
    cleaned_codes: list[str] = field(default_factory=list)


# --- the transcript -----------------------------------------------------------------------------


def check_transcript(text: str) -> None:
    if not text.strip():
        raise AnswerRefused("no_transcript", "The recording has no transcript to read.")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise AnswerRefused(
            "transcript_too_long",
            f"The transcript has more than {MAX_TRANSCRIPT_CHARS:,} characters, too long to read.",
        )


# --- finding a quote in the transcript ----------------------------------------------------------

_INVISIBLE = {"​", "‌", "‍", "⁠", "﻿"}


def normalise(text: str) -> str:
    """The text with case, punctuation and spacing ignored - and nothing else. Letters, digits and
    the vowel signs of Indic scripts are kept, so a different word never matches. Joiners and other
    invisible characters are dropped (a conjunct is the same with or without one)."""
    kept: list[str] = []
    for ch in unicodedata.normalize("NFC", text).casefold():
        if ch in _INVISIBLE:
            continue
        kept.append(ch if unicodedata.category(ch)[0] in "LMN" else " ")
    return " ".join("".join(kept).split())


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def locate_quote(
    segments: object, quote: str, start_ms: int, end_ms: int
) -> tuple[int, int] | None:
    """The (start, end) in milliseconds of the transcript lines that hold ``quote``, or None when
    the words are not in the lines near the time the model named. The time returned is the
    transcript's own, not the model's. Stored segments came from a speech service and are not
    trusted: anything that is not a well-formed segment is skipped."""
    wanted = normalise(quote)
    if not wanted or not isinstance(segments, list):
        return None
    low, high = start_ms - TIME_SLACK_MS, end_ms + TIME_SLACK_MS
    joined = ""
    spans: list[tuple[int, int, int, int]] = []  # text start, text end, ms start, ms end
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        begin, end = _number(segment.get("start")), _number(segment.get("end"))
        text = segment.get("text")
        if begin is None or end is None or not isinstance(text, str):
            continue
        a, b = round(begin * 1000), round(end * 1000)
        piece = normalise(text)
        if not piece or b <= low or a >= high:
            continue
        offset = len(joined) + (1 if joined else 0)
        joined = f"{joined} {piece}" if joined else piece
        spans.append((offset, offset + len(piece), a, b))
    at = joined.find(wanted)
    if at < 0:
        return None
    last = at + len(wanted) - 1
    first_ms = next(a for lo, hi, a, _b in spans if lo <= at < hi or at < lo)
    last_ms = next(b for lo, hi, _a, b in spans if lo <= last < hi or last < lo)
    return first_ms, last_ms


# --- verifying an answer ------------------------------------------------------------------------


def _refuse(message: str) -> AnswerRefused:
    return AnswerRefused("bad_answer", message)


def _whole(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _refuse(f"The {name} time must be a whole number of milliseconds.")
    return value


def _text(value: object, name: str, longest: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _refuse(f"The {name} must be text.")
    if len(value) > longest:
        raise _refuse(f"The {name} may have at most {longest} characters.")
    return value


def _check_shape(claim: Claim, keys: set[str]) -> None:
    if claim.field not in keys:
        raise _refuse("A field that is not part of this checklist was answered.")
    if claim.state not in STATES:
        raise _refuse("A line has a state that does not exist.")
    value = _text(claim.value, "value", MAX_VALUE)
    quote = _text(claim.quote, "quote", MAX_QUOTE)
    reason = _text(claim.reason, "reason", MAX_REASON)
    start, end = _whole(claim.start_ms, "start"), _whole(claim.end_ms, "end")
    if (start is None) != (end is None):
        raise _refuse("A quote needs both a start and an end time.")
    present = {
        "value": value is not None,
        "quote": quote is not None,
        "times": start is not None,
        "reason": reason is not None,
    }
    expected = {
        "unknown": dict.fromkeys(present, False),
        "stated": {"value": True, "quote": True, "times": True, "reason": False},
        "assumed": {"value": True, "quote": True, "times": True, "reason": True},
    }[claim.state]
    if present != expected:
        raise _refuse(f"A {claim.state} line has the wrong parts.")


def _clean(text: str, codes: set[str]) -> str:
    result = screen(text)
    codes.update(finding.code for finding in result.findings)
    return " ".join(result.clean.split())


def _meaningful(text: str) -> int:
    return sum(1 for ch in text if unicodedata.category(ch)[0] in "LMN")


def _check_quote(
    segments: object, quote: str, start_ms: int, end_ms: int
) -> tuple[tuple[int, int] | None, str | None]:
    """The transcript time of a quote, or why it cannot be used."""
    if _meaningful(quote) < MIN_QUOTE_CHARS:
        return None, "quote_too_short"
    if start_ms < 0 or end_ms <= start_ms or end_ms - start_ms > MAX_WINDOW_MS:
        return None, "bad_time"
    found = locate_quote(segments, quote, start_ms, end_ms)
    if found is None:
        return None, "quote_not_found"
    # One very long transcript line would make "the moment to listen to" meaningless.
    return (found, None) if found[1] - found[0] <= MAX_SPAN_MS else (None, "bad_time")


def _unknown(field_key: str, code: str | None) -> Line:
    return Line(field_key, "unknown", None, None, None, None, None, code)


def verify(
    framework: str,
    claims: list[Claim],
    notes: list[NoteClaim],
    segments: object,
) -> Verified:
    """Check a model's answer against the transcript. Raises ``AnswerRefused`` for an answer that is
    badly formed or mostly unverifiable; otherwise returns one line per checklist field (in the
    frame's order, the unanswered ones unknown) followed by the notes whose quotes were found."""
    fields = FRAMEWORKS.get(framework)
    if fields is None:
        raise _refuse("The checklist frame does not exist.")
    if len(notes) > MAX_NOTES:
        raise _refuse(f"At most {MAX_NOTES} notes are accepted.")
    keys = {f.key for f in fields}
    by_field: dict[str, Claim] = {}
    for claim in claims:
        _check_shape(claim, keys)
        if claim.field in by_field:
            raise _refuse("A field was answered twice.")
        by_field[claim.field] = claim

    codes: set[str] = set()
    downgraded = 0
    claimed = 0
    lines: list[Line] = []
    for item in fields:
        answer = by_field.get(item.key)
        if answer is None or answer.state == "unknown":
            lines.append(_unknown(item.key, None))
            continue
        claimed += 1
        # _check_shape guaranteed these parts are present (the "or" only calms the type checker).
        claim = answer
        quote = _clean(claim.quote or "", codes)
        value = _clean(claim.value or "", codes)
        reason = _clean(claim.reason, codes) if claim.reason else None
        found, code = _check_quote(segments, quote, claim.start_ms or 0, claim.end_ms or 0)
        if (
            code is None
            and claim.state == "stated"
            and (not normalise(value) or normalise(value) not in normalise(quote))
        ):
            code = "value_not_in_quote"
        if code is not None or found is None:
            downgraded += 1
            lines.append(_unknown(item.key, code))
            continue
        lines.append(Line(item.key, claim.state, value, quote, found[0], found[1], reason, None))

    dropped = 0
    for entry in notes:
        text = _text(entry.text, "note", MAX_NOTE_TEXT)
        quote_raw = _text(entry.quote, "quote", MAX_QUOTE)
        start, end = _whole(entry.start_ms, "start"), _whole(entry.end_ms, "end")
        if text is None or quote_raw is None or start is None or end is None:
            raise _refuse("A note needs its text, a quote and both times.")
        claimed += 1
        quote = _clean(quote_raw, codes)
        found, code = _check_quote(segments, quote, start, end)
        if code is not None or found is None:
            dropped += 1
            continue
        lines.append(
            Line(NOTE, "stated", _clean(text, codes), quote, found[0], found[1], None, None)
        )

    if (downgraded + dropped) * 2 > claimed:
        raise AnswerRefused(
            "unverified_answer",
            "Most of the quotes in the answer could not be found in the transcript.",
        )
    return Verified(lines, downgraded, dropped, sorted(codes))


# --- what may become a proposal -----------------------------------------------------------------


def proposal_key(framework: str, line: Line) -> str | None:
    """The buyer-memory key a checked line could be proposed under, or None. Only a stated or
    assumed line of a field with a reviewed mapping qualifies; a proposal is always an
    assumption."""
    if line.field == NOTE or line.state == "unknown":
        return None
    for item in FRAMEWORKS.get(framework, ()):
        if item.key == line.field:
            return item.memory_key
    return None
