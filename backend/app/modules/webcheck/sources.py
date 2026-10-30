"""The catalogue of sources and their parsers (ADR 0019).

A source names ONE host and builds the address itself; the model and the user only give a query,
which must match the source's pattern. A parser turns a page into a ``CheckRecord`` or says
"unclear". Parsers are deterministic: no model reads a page.

v1 has only DEMO sources. A real source is added in a later step, after the owner has read that
site's terms of use and robots.txt (ADR 0019, W2) - and is then switched on per deployment.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import quote

from app.core.webfetch import FetchResult
from app.modules.webcheck.fake import DEMO_HOST
from app.modules.webcheck.rules import (
    MAX_RESULTS_READ,
    NAME_MAX,
    STATUSES,
    CheckRecord,
    InvalidQueryError,
    build_excerpt,
    clean_text,
    merge_codes,
    unclear,
)

Parser = Callable[[FetchResult, str], CheckRecord]


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    kind: Literal["rera", "company"]
    host: str
    # What the site's terms say about automated access, as read by the owner. Shown to admins.
    terms_note: str
    demo: bool
    query_pattern: re.Pattern[str]
    query_hint: str
    path_template: str  # "/rera/search?number={q}"
    parser: Parser

    def check_query(self, query: str) -> str:
        """The query in its tidy form, or ``InvalidQueryError``. Only a public identifier passes:
        letters, digits and a few signs - never a link, a line break or a hidden character."""
        text = re.sub(" +", " ", query.strip())
        if not self.query_pattern.fullmatch(text):
            raise InvalidQueryError(self.query_hint)
        return text

    def url_for(self, query: str) -> str:
        """The address, built here: the query goes into the query string, percent-encoded."""
        return f"https://{self.host}{self.path_template.format(q=quote(query, safe=''))}"

    def parse(self, result: FetchResult, query: str) -> CheckRecord:
        return self.parser(result, query)


# --- parsing an HTML result table ---------------------------------------------------------------


class _ResultPage(HTMLParser):
    """Reads ``<table id="result">`` rows as (label, value) and the ``no-result`` message."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables = 0
        self.rows: list[list[str]] = []
        self.no_result: str | None = None
        self._in_table = False
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._no_result: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "table" and values.get("id") == "result":
            self._in_table = True
            self.tables += 1
        elif tag == "tr" and self._in_table:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "p" and "no-result" in (values.get("class") or ""):
            self._no_result = []
        elif self._cell is not None and tag == "img" and values.get("src"):
            self._cell.append(f" ![]({values['src']}) ")  # kept as text, so screening reports it
        elif self._cell is not None and tag == "a" and values.get("href"):
            self._cell.append(f" {values['href']} ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._in_table = False
        elif tag == "p" and self._no_result is not None:
            self.no_result = "".join(self._no_result)
            self._no_result = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._no_result is not None:
            self._no_result.append(data)


def _label(text: str) -> str:
    return re.sub(r"[\s_]+", " ", text).strip().lower()


def _not_a_normal_answer(result: FetchResult, content_type: str) -> CheckRecord | None:
    if result.status != 200:
        return unclear(f"The site answered with status {result.status}.")
    if result.content_type != content_type:
        return unclear("The page is not in the expected format.")
    return None


def parse_rera_page(result: FetchResult, query: str) -> CheckRecord:
    """A RERA page: found (with the status the page gives), not found, or unclear."""
    refused = _not_a_normal_answer(result, "text/html")
    if refused is not None:
        return refused
    page = _ResultPage()
    page.feed(result.body.decode("utf-8", errors="replace"))
    page.close()
    if page.tables == 0:
        if page.no_result is not None:
            message, message_codes = clean_text(page.no_result, 200)
            return CheckRecord("not_found", None, None, None, message, tuple(message_codes))
        return unclear("The page layout was not recognised.")

    rows: dict[str, str] = {}
    for row in page.rows:
        if len(row) < 2:
            continue
        label = _label(row[0])
        if label in rows:
            return unclear("The page repeats a field, so it cannot be read with certainty.")
        rows[label] = row[1]
    registration = rows.get("registration", "").strip().upper()
    if not registration or registration != query.strip().upper():
        return unclear("The page does not show the registration that was asked for.")
    status = rows.get("status", "").strip().lower().replace(" ", "_")
    if status not in STATUSES:
        return unclear("The page does not give a status that is understood.")
    valid_until: date | None = None
    if "valid until" in rows:
        try:
            valid_until = date.fromisoformat(rows["valid until"].strip())
        except ValueError:
            return unclear("The page gives a date that is not understood.")
    name: str | None = None
    codes: list[str] = []
    if "project" in rows:
        name, codes = clean_text(rows["project"], NAME_MAX)
    fields = [("Registration", registration), ("Project", name or "-"), ("Status", status)]
    if valid_until is not None:
        fields.append(("Valid until", valid_until.isoformat()))
    return CheckRecord(
        "found", name or None, status, valid_until, build_excerpt(fields), merge_codes(codes)
    )


# --- parsing a JSON company list ----------------------------------------------------------------


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def parse_company_json(result: FetchResult, query: str) -> CheckRecord:
    """A list of companies: one exact match is found, none is not found, several is unclear."""
    refused = _not_a_normal_answer(result, "application/json")
    if refused is not None:
        return refused
    try:
        data: Any = json.loads(result.body.decode("utf-8", errors="replace"))
    except ValueError:
        return unclear("The answer is not valid JSON.")
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return unclear("The answer does not have the expected shape.")
    items = data["results"][:MAX_RESULTS_READ]
    if not data["results"]:
        return CheckRecord("not_found", None, None, None, "No company found.")
    names: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return unclear("An entry in the answer could not be read.")
        names.append(item)
    exact = [item for item in names if _same_name(item["name"], query)]
    if not exact:
        return CheckRecord(
            "not_found", None, None, None, "No company with exactly this name was found."
        )
    if len(exact) > 1:
        return unclear("More than one company has exactly this name.")
    status = str(exact[0].get("status", "")).strip().lower().replace(" ", "_")
    if status not in STATUSES:
        return unclear("The answer does not give a status that is understood.")
    name, codes = clean_text(exact[0]["name"], NAME_MAX)
    excerpt = build_excerpt([("Name", name), ("Status", status)])
    return CheckRecord("found", name, status, None, excerpt, merge_codes(codes))


# --- the catalogue ------------------------------------------------------------------------------

_DEMO_NOTE = (
    "Demo source: a fictional registry served inside the CRM for tests and local trials. "
    "It never contacts a real site."
)

SOURCES: dict[str, Source] = {
    "demo_rera": Source(
        key="demo_rera",
        title="Demo RERA registry",
        kind="rera",
        host=DEMO_HOST,
        terms_note=_DEMO_NOTE,
        demo=True,
        query_pattern=re.compile(r"[A-Za-z0-9][A-Za-z0-9/\-]{4,39}", re.ASCII),
        query_hint="A RERA number has 5 to 40 letters, digits, '/' or '-'.",
        path_template="/rera/search?number={q}",
        parser=parse_rera_page,
    ),
    "demo_company": Source(
        key="demo_company",
        title="Demo company registry",
        kind="company",
        host=DEMO_HOST,
        terms_note=_DEMO_NOTE,
        demo=True,
        query_pattern=re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,&'()\-]{2,119}", re.ASCII),
        query_hint="A company name has 3 to 120 letters, digits, spaces or . , & ' ( ) -",
        path_template="/api/companies?name={q}",
        parser=parse_company_json,
    ),
}


def enabled_sources(*, configured: list[str], demo: bool) -> dict[str, Source]:
    """The sources this deployment may use: the configured keys, plus every demo source when
    ``demo`` is on. An unknown key is an error (a typo must not silently switch nothing on)."""
    chosen: dict[str, Source] = {}
    for key in configured:
        if key not in SOURCES:
            raise ValueError(f"unknown web check source: {key}")
        chosen[key] = SOURCES[key]
    if demo:
        chosen.update({key: source for key, source in SOURCES.items() if source.demo})
    return chosen
