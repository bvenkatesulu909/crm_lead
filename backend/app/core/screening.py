"""Screening of untrusted text before it reaches a model or an approver (ADR 0017, S6).

``screen(text)`` returns the text cleaned and a list of what was found. It is a pure function:
no database, no model, no network, the same answer for the same input.

What it takes out of the CLEAN text: hidden and control characters, HTML comments / scripts /
tags, images, links and e-mail addresses (each replaced by a visible marker, so a reader can see
that something was there), and text that repeats itself in order to push a real sentence out of
sight. What it only REPORTS (the text stays, because deleting words would change their
meaning): phrases that read like instructions to an AI.

Findings carry a stable ``code`` and a plain sentence; they never repeat the text they found.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

LINK_PLACEHOLDER = "[link removed]"
IMAGE_PLACEHOLDER = "[image removed]"
ADDRESS_PLACEHOLDER = "[address removed]"
REPEAT_PLACEHOLDER = "[repeated text removed]"

# Limits for "text that repeats itself".
MAX_LINE_REPEATS = 5
MAX_WORD_RUN = 20
MAX_CHAR_RUN = 200

MESSAGES = {
    "hidden_characters": "The text contains invisible characters.",
    "control_characters": "The text contains control characters.",
    "html_markup": "The text contains HTML markup.",
    "external_image": "The text contains an image from outside.",
    "link": "The text contains a link.",
    "email_address": "The text contains an e-mail address.",
    "repeated_text": "The text repeats itself many times.",
    "instruction_phrase": "The text contains words that read like instructions to an AI.",
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


@dataclass(frozen=True)
class Screened:
    clean: str
    findings: list[Finding]


# --- hidden characters -------------------------------------------------------------------------

_JOINERS = {"‌", "‍"}  # needed inside Indic scripts, so judged by their neighbours
_TAGS = range(0xE0000, 0xE0080)  # "tag" characters: ASCII in disguise


def _is_hidden(char: str) -> bool:
    return unicodedata.category(char) == "Cf" and char not in _JOINERS


def _is_control(char: str) -> bool:
    return unicodedata.category(char) == "Cc" and char not in "\n\r\t"


def _ascii_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _joiner_is_suspicious(text: str, i: int) -> bool:
    """A joiner between ASCII letters, or several in a row, hides something; one inside a
    word of another script is ordinary."""
    before = text[i - 1] if i > 0 else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    return (
        _ascii_alnum(before)
        or _ascii_alnum(after)
        or before in _JOINERS
        or after in _JOINERS
        or _is_hidden(before)
        or _is_hidden(after)
    )


def _strip_hidden(text: str) -> tuple[str, bool, bool]:
    """(text without hidden/control characters, found hidden, found control)."""
    out: list[str] = []
    hidden = control = False
    for i, char in enumerate(text):
        if char in _JOINERS:
            if _joiner_is_suspicious(text, i):
                hidden = True
                continue
        elif _is_hidden(char):
            hidden = True
            continue
        elif _is_control(char):
            control = True
            continue
        out.append(char)
    return "".join(out), hidden, control


_TAG_RUN = re.compile("[󠀀-󠁿]+")


def _decode_tags(text: str) -> str:
    """Invisible tag characters spell ASCII; read each run as the letters it stands for, set
    apart by spaces (it was hidden next to other text)."""

    def read(match: re.Match[str]) -> str:
        letters = "".join(
            chr(ord(c) - 0xE0000) for c in match.group(0) if 0x20 <= ord(c) - 0xE0000 < 0x7F
        )
        return f" {letters} "

    return _TAG_RUN.sub(read, text)


# --- patterns ----------------------------------------------------------------------------------

_FLAGS = re.IGNORECASE
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1\s*>", re.DOTALL | _FLAGS)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*>", _FLAGS)
_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:[a-z][a-z0-9+.-]*:|//)[^)\s]*\)", _FLAGS)
_SCHEME_URL = re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://[^\s<>\"')\]]+", _FLAGS)
_WWW = re.compile(r"\bwww\.[^\s<>\"')\]]+", _FLAGS)
_DATA_URI = re.compile(r"\bdata:[a-z]+/[a-z0-9.+-]+[;,][^\s<>\"')\]]*", _FLAGS)
_UNIT_TLDS = {"ft", "in", "sq", "mt", "kg", "cm", "mm", "km", "ml"}
_DOMAIN_PATH = re.compile(r"\b(?:[a-z0-9-]+\.)+([a-z]{2,24})/[^\s<>\"')\]]*", _FLAGS)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")

_ROLE_LINE = re.compile(r"^\s*(?:system|assistant|developer)\s*:", re.MULTILINE)
_INSTRUCTION_PATTERNS = [
    re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass)\s+"
        r"(?:(?:all|any|the|your|these|those|my|previous|prior|above|earlier|safety|system)\s+)*"
        r"(?:instructions?|rules?|prompts?|guidelines?|directions?)\b"
    ),
    re.compile(r"\b(?:ignore|disregard)\s+the\s+above\b"),
    re.compile(
        r"\byou are now\s+(?:in\s+)?(?:an?\s+|the\s+)?"
        r"(?:admin|administrator|developer|dev|debug|god|root|system|unrestricted|jailbroken|dan)\b"
    ),
    re.compile(
        r"\b(?:reveal|print|show|output|repeat|display|leak)\s+(?:me\s+)?(?:your|the)\s+"
        r"(?:system\s+|initial\s+|hidden\s+)?(?:prompt|instructions)\b"
    ),
    re.compile(r"\bsystem prompt\b"),
    re.compile(r"\bnew instructions?\s*:"),
    re.compile(r"\[/?inst\]|<\|im_(?:start|end)\|>|<\|(?:system|user|assistant)\|>"),
    re.compile(
        r"\bdo(?: not|n't)\s+(?:tell|inform|mention|reveal)\s+(?:this\s+to\s+)?"
        r"(?:the\s+)?(?:user|customer|manager|approver)\b"
    ),
    re.compile(r"\bact as\s+(?:the\s+|an?\s+)?(?:system|admin|administrator|root|developer)\b"),
    re.compile(
        r"\b(?:assign|send|forward|export|email|mail)\s+(?:all|every|each)\s+(?:the\s+)?"
        r"(?:leads?|contacts?|customers?|records?|data)\b"
    ),
    re.compile(r"\bjailbreak\b|\bdeveloper message\b"),
]


def _normalised(text: str, *, keep_lines: bool = False) -> str:
    """The text as a model would read it: no hidden characters, tags decoded, NFKC, lower case."""
    visible, _, _ = _strip_hidden(_decode_tags(text))
    folded = unicodedata.normalize("NFKC", visible).lower()
    if keep_lines:
        return folded
    return re.sub(r"\s+", " ", folded).strip()


def find_instructions(text: str) -> list[str]:
    """Short snippets (lower case, at most 60 characters) of text that reads like an
    instruction to an AI. The caller decides what to do; the text itself is not changed."""
    hits: list[str] = []
    flat = _normalised(text)
    for pattern in _INSTRUCTION_PATTERNS:
        hits.extend(m.group(0)[:60] for m in pattern.finditer(flat))
    lines = _normalised(text, keep_lines=True)
    hits.extend(m.group(0).strip()[:60] for m in _ROLE_LINE.finditer(lines))
    return list(dict.fromkeys(hits))


# --- repeated text -----------------------------------------------------------------------------


def _collapse_repeats(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    counts: dict[str, int] = {}
    for line in lines:
        key = line.strip()
        if len(key) >= 3:
            counts[key] = counts.get(key, 0) + 1
    kept: list[str] = []
    done: set[str] = set()
    changed = False
    for line in lines:
        key = line.strip()
        if counts.get(key, 0) > MAX_LINE_REPEATS:
            changed = True
            if key in done:
                continue
            done.add(key)
            kept.extend([line, REPEAT_PLACEHOLDER])
            continue
        kept.append(line)
    text = "\n".join(kept)

    def shorten_word_run(match: re.Match[str]) -> str:
        return f"{match.group(1)} {REPEAT_PLACEHOLDER}"

    runs = re.compile(rf"(\b\w+\b)(?:\s+\1\b){{{MAX_WORD_RUN},}}", _FLAGS)
    new = runs.sub(shorten_word_run, text)
    changed = changed or new != text
    text = new
    chars = re.compile(rf"(\S)\1{{{MAX_CHAR_RUN},}}")
    new = chars.sub(lambda m: f"{m.group(1) * 3} {REPEAT_PLACEHOLDER}", text)
    return new, changed or new != text


# --- the function ------------------------------------------------------------------------------


def screen(text: str, *, strip_links: bool = True, strip_addresses: bool = True) -> Screened:
    """Clean ``text`` and report what was found.

    By default everything is taken out. Text a person TYPED keeps its links and addresses
    (``strip_links=False, strip_addresses=False``: people paste them); record text keeps its
    e-mail addresses (they are data) but loses links (``strip_addresses=False``)."""
    if not isinstance(text, str):
        raise TypeError("screen() needs text")
    codes: list[str] = []

    def found(code: str) -> None:
        if code not in codes:
            codes.append(code)

    work, hidden, control = _strip_hidden(text)
    if hidden:
        found("hidden_characters")
    if control:
        found("control_characters")
    instructions_seen = bool(find_instructions(text))

    # 1. comments and scripts go with their content
    new = _COMMENT.sub("", work)
    new = _SCRIPT.sub("", new)
    if new != work:
        found("html_markup")
    work = new
    # 2. images
    new = _MD_IMAGE.sub(IMAGE_PLACEHOLDER, work)
    new = _HTML_IMAGE.sub(IMAGE_PLACEHOLDER, new)
    if new != work:
        found("external_image")
    work = new
    # 3. addresses, then links
    if strip_addresses:
        new = _EMAIL.sub(ADDRESS_PLACEHOLDER, work)
        if new != work:
            found("email_address")
        work = new
    if strip_links:
        before = work
        work = _MD_LINK.sub(lambda m: f"{m.group(1)} {LINK_PLACEHOLDER}".strip(), work)
        work = _SCHEME_URL.sub(LINK_PLACEHOLDER, work)
        work = _WWW.sub(LINK_PLACEHOLDER, work)
        work = _DATA_URI.sub(LINK_PLACEHOLDER, work)
        work = _DOMAIN_PATH.sub(
            lambda m: m.group(0) if m.group(1).lower() in _UNIT_TLDS else LINK_PLACEHOLDER, work
        )
        if work != before:
            found("link")
    # 4. the tags that are left (their text stays)
    new = _TAG.sub("", work)
    if new != work:
        found("html_markup")
    work = new
    # 5. text that repeats itself
    work, repeated = _collapse_repeats(work)
    if repeated:
        found("repeated_text")
    if instructions_seen:
        found("instruction_phrase")
    return Screened(work, [Finding(code, MESSAGES[code]) for code in codes])


def clean_records(value: Any) -> tuple[Any, bool]:
    """Clean every text inside a structure of dicts, lists and strings that comes out of the CRM
    on its way into a prompt: hidden characters, markup, images, links and floods go; e-mail
    addresses stay (they are data). Returns the cleaned copy (the original is not changed) and
    whether any text read like an instruction to an AI."""
    suspicious = False

    def walk(item: Any) -> Any:
        nonlocal suspicious
        if isinstance(item, str):
            result = screen(item, strip_addresses=False)
            suspicious = suspicious or any(f.code == "instruction_phrase" for f in result.findings)
            return result.clean
        if isinstance(item, dict):
            return {key: walk(inner) for key, inner in item.items()}
        if isinstance(item, (list, tuple)):
            return [walk(inner) for inner in item]
        return item

    return walk(value), suspicious
