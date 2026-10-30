"""Pure rules of the web check (ADR 0019): what a result looks like and how text from a page is
made safe. No database, no network."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.core.screening import screen

Verdict = Literal["found", "not_found", "unclear"]

# The only statuses a parser accepts. A page that says anything else is "unclear": the parser
# never guesses what an unknown word means.
STATUSES = frozenset(
    {
        "active",
        "expired",
        "revoked",
        "suspended",
        "lapsed",
        "struck_off",
        "dormant",
        "liquidation",
    }
)
NAME_MAX = 200
EXCERPT_MAX = 4096
MAX_RESULTS_READ = 5  # a long list is not walked to the end


@dataclass(frozen=True)
class CheckRecord:
    """What a parser makes of a page. ``excerpt`` is built from the parsed fields, never copied
    from the raw page; every text here has been through ``screen()``."""

    verdict: Verdict
    registered_name: str | None
    status: str | None
    valid_until: date | None
    excerpt: str
    # The kinds of finding when text had to be cleaned (``link``, ``instruction_phrase``, ...).
    cleaned: tuple[str, ...] = ()


class InvalidQueryError(ValueError):
    """The search text is not in the shape this source accepts. The text itself is not repeated."""

    def __init__(self, hint: str) -> None:
        super().__init__(f"The search text is not valid for this source. {hint}")


def clean_text(text: str, cap: int) -> tuple[str, list[str]]:
    """Text from a page, safe to keep and to show: hidden characters, markup, images, links and
    addresses out, one line, capped. Returns the text and the kinds of finding."""
    screened = screen(text)
    flat = re.sub(r"\s+", " ", screened.clean).strip()
    return flat[:cap], [finding.code for finding in screened.findings]


def unclear(reason: str) -> CheckRecord:
    """The page could not be read with certainty. ``reason`` is a fixed sentence of ours."""
    return CheckRecord("unclear", None, None, None, reason)


def merge_codes(*groups: list[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for group in groups:
        for code in group:
            if code not in seen:
                seen.append(code)
    return tuple(seen)


def build_excerpt(fields: list[tuple[str, str]]) -> str:
    """ "Label: value; Label: value" from parsed fields, within the cap."""
    return "; ".join(f"{label}: {value}" for label, value in fields)[:EXCERPT_MAX]
