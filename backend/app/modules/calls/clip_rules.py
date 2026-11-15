"""Pure rules of call highlight clips (ADR 0033): how long a clip may be, what a person may type
into it and which transcript lines belong to it. No database, no ffmpeg, no network."""

import re
from dataclasses import dataclass

from app.core.screening import screen

MIN_MS = 3_000
MAX_MS = 120_000
TITLE_MAX = 100
NOTE_MAX = 500
EXCERPT_MAX = 4_000
LINE_MAX = 600
MARKER = "…"
# What the screening puts where it took a link or an address out.
_REMOVED = re.compile(r"\[(?:link|address) removed\]")


class ClipRuleError(ValueError):
    """A clip (or its texts) that breaks a rule."""


@dataclass(frozen=True)
class Cleaned:
    """A typed text after cleaning, and the KINDS of finding (never the text itself)."""

    text: str | None
    findings: list[str]


def _whole(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClipRuleError("The start and the end must be whole numbers of milliseconds.")
    return value


def check_range(start_ms: int, end_ms: int, *, duration_seconds: int | None) -> None:
    """The moment must lie inside the recording and be between 3 and 120 seconds long."""
    start, end = _whole(start_ms), _whole(end_ms)
    if start < 0:
        raise ClipRuleError("The clip cannot start before the recording does.")
    if end <= start:
        raise ClipRuleError("The clip must end after it starts.")
    if end - start < MIN_MS:
        raise ClipRuleError(f"A clip is at least {MIN_MS // 1000} seconds long.")
    if end - start > MAX_MS:
        raise ClipRuleError(f"A clip is at most {MAX_MS // 1000} seconds long.")
    if duration_seconds is None:
        raise ClipRuleError("The length of the recording is not known yet.")
    if end > duration_seconds * 1000:
        raise ClipRuleError("The clip must end inside the recording.")


def _clean(raw: object, limit: int, what: str) -> Cleaned:
    if raw is None:
        return Cleaned(None, [])
    if not isinstance(raw, str):
        raise ClipRuleError(f"The {what} must be text.")
    if len(raw.strip()) > limit:
        raise ClipRuleError(f"The {what} is longer than {limit} characters.")
    screened = screen(raw)
    text = " ".join(screened.clean.split())
    return Cleaned(text or None, [finding.code for finding in screened.findings])


def clean_title(raw: object) -> Cleaned:
    """The title: required, up to 100 characters, links, markup and hidden text taken out. A title
    that is nothing once cleaned (empty, or only a link) is refused. An instruction-like text is
    kept but reported."""
    cleaned = _clean(raw, TITLE_MAX, "title")
    if cleaned.text is None or not _REMOVED.sub("", cleaned.text).strip():
        raise ClipRuleError("The clip needs a title.")
    return cleaned


def clean_note(raw: object) -> Cleaned:
    """The note: optional, up to 500 characters, cleaned like the title."""
    return _clean(raw, NOTE_MAX, "note")


def _stamp(seconds: float) -> str:
    whole = int(seconds)
    return f"[{whole // 60}:{whole % 60:02d}]"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def excerpt(segments: object, start_ms: int, end_ms: int) -> str:
    """The transcript lines that overlap the range, each with its start time, cleaned and capped. A
    line that only touches the edge is left out. Anything that is not a well-formed segment is
    skipped: the stored segments came from a speech service, so they are not trusted."""
    if not isinstance(segments, list):
        return ""
    start, end = start_ms / 1000, end_ms / 1000
    lines: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        a, b, text = _number(segment.get("start")), _number(segment.get("end")), segment.get("text")
        if a is None or b is None or not isinstance(text, str):
            continue
        if b <= start or a >= end:
            continue
        cleaned = " ".join(screen(text, strip_links=False, strip_addresses=False).clean.split())
        if cleaned:
            lines.append(f"{_stamp(a)} {cleaned[:LINE_MAX]}")
    joined = "\n".join(lines)
    if len(joined) > EXCERPT_MAX:
        joined = joined[: EXCERPT_MAX - len(MARKER)] + MARKER
    return joined
