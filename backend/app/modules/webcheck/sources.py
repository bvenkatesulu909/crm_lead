"""The catalogue of sources and their parsers (ADR 0019).

A source names ONE host and builds the address itself; the model and the user only give a query,
which must match the source's pattern. A parser turns a page into a ``CheckRecord`` or says
"unclear". Parsers are deterministic: no model reads a page.

A real source is added only after the owner has read that site's terms of use and robots.txt
(ADR 0019, W2), and is then switched on per deployment. The first one is AP RERA, whose search is
a web form (ADR 0019, Amendment A): it is fetched with ``form_search`` instead of an address.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import quote

from app.core.webfetch import FetchResult, FormSpec
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
    path_template: str  # "/rera/search?number={q}"; unused when ``form`` is set
    parser: Parser
    # A source whose search is a web form (ADR 0019, Amendment A): fetched with ``form_search``.
    form: FormSpec | None = field(default=None)
    # Registration numbers that are written in capitals on the registry (e.g. AP RERA's "P...").
    upper_case: bool = False

    def check_query(self, query: str) -> str:
        """The query in its tidy form, or ``InvalidQueryError``. Only a public identifier passes:
        letters, digits and a few signs - never a link, a line break or a hidden character."""
        text = re.sub(" +", " ", query.strip())
        if not self.query_pattern.fullmatch(text):
            raise InvalidQueryError(self.query_hint)
        return text.upper() if self.upper_case else text

    def url_for(self, query: str) -> str:
        """The address, built here: the query goes into the query string, percent-encoded. A form
        source has one fixed page; the query travels in the form, not in the address."""
        if self.form is not None:
            return f"https://{self.host}{self.form.path}"
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


# --- the AP RERA results page (ADR 0019, Amendment A) -------------------------------------------

APRERA_TABLE_ID = "ContentPlaceHolder1_gvApprovedProject"
APRERA_NO_RESULT_ID = "ContentPlaceHolder1_Label1"
APRERA_NO_RESULT = "no data found on your entered text"
APRERA_COLUMNS = (
    "s.no.",
    "application no",
    "registration no",
    "project name",
    "promoter name",
    "place",
    "status",
)
# The only status words understood, and what is stored for them. Anything else is "unclear".
APRERA_STATUSES = {"aprera registered": "registered"}
APRERA_MAX_ROWS = 50  # a search by one number returns one row; a long table is not walked


class _GridPage(HTMLParser):
    """Reads one table, found by its id: the header cells and each body row's cells as text,
    plus the text of one message element (also found by its id). Scripts and styles are skipped;
    a link or picture inside a cell is kept as text, so the cleaning reports it."""

    def __init__(self, table_id: str, message_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self._table_id = table_id
        self._message_id = message_id
        self.tables = 0
        self.header: list[str] = []
        self.rows: list[list[str]] = []
        self.message: str | None = None
        self.too_many = False
        self._depth = 0  # how deep inside the wanted table (nested tables are not ours)
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._header_row = False
        self._message: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "table" and values.get("id") == self._table_id and self._depth == 0:
            self.tables += 1
            self._depth = 1
        elif tag == "table" and self._depth:
            self._depth += 1
        elif tag == "tr" and self._depth == 1:
            self._row, self._header_row = [], False
        elif tag in ("td", "th") and self._row is not None and self._depth == 1:
            self._cell = []
            self._header_row = self._header_row or tag == "th"
        elif values.get("id") == self._message_id and self.message is None:
            self._message = []
        elif self._cell is not None and tag == "img" and values.get("src"):
            self._cell.append(f" ![]({values['src']}) ")
        elif self._cell is not None and tag == "a" and values.get("href"):
            self._cell.append(f" {values['href']} ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._depth == 1:
            if self._header_row and not self.header:
                self.header = self._row
            elif len(self.rows) < APRERA_MAX_ROWS:
                self.rows.append(self._row)
            else:
                self.too_many = True
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
        elif tag == "span" and self._message is not None:
            self.message = " ".join("".join(self._message).split())
            self._message = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._message is not None:
            self._message.append(data)


def parse_aprera_results(result: FetchResult, query: str) -> CheckRecord:
    """The AP RERA approved-project search: found (registered), not found, or unclear. Only the
    row whose Registration No equals the query is read; anything unexpected is "unclear"."""
    refused = _not_a_normal_answer(result, "text/html")
    if refused is not None:
        return refused
    page = _GridPage(APRERA_TABLE_ID, APRERA_NO_RESULT_ID)
    page.feed(result.body.decode("utf-8", errors="replace"))
    page.close()
    if page.tables == 0:
        if page.message is not None and page.message.casefold() == APRERA_NO_RESULT:
            return CheckRecord(
                "not_found", None, None, None, "No approved project with this number was found."
            )
        return unclear("The page layout was not recognised.")
    if page.tables > 1 or page.too_many:
        return unclear("The page layout was not recognised.")
    if tuple(cell.casefold() for cell in page.header) != APRERA_COLUMNS:
        return unclear("The results table has changed, so it cannot be read with certainty.")
    if any(len(row) != len(APRERA_COLUMNS) for row in page.rows):
        return unclear("A row of the results table could not be read.")
    wanted = query.strip().upper()
    matches = [row for row in page.rows if row[2].strip().upper() == wanted]
    if not matches:
        return CheckRecord(
            "not_found", None, None, None, "No approved project with this number was found."
        )
    if len(matches) > 1:
        return unclear("The number appears more than once, so it cannot be read with certainty.")
    _, _, registration, project, promoter, place, status_text = matches[0]
    status = APRERA_STATUSES.get(" ".join(status_text.split()).casefold())
    if status is None:
        return unclear("The page does not give a status that is understood.")
    name, name_codes = clean_text(project, NAME_MAX)
    promoter_text, promoter_codes = clean_text(promoter, NAME_MAX)
    place_text, place_codes = clean_text(place, NAME_MAX)
    fields = [
        ("Registration", registration.strip().upper()),
        ("Project", name or "-"),
        ("Promoter", promoter_text or "-"),
        ("Place", place_text or "-"),
        ("Status", "APRERA Registered"),
    ]
    return CheckRecord(
        "found",
        name or None,
        status,
        None,
        build_excerpt(fields),
        merge_codes(name_codes, promoter_codes, place_codes),
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

_APRERA_NOTE = (
    "AP RERA terms of use (rera.ap.gov.in/RERA/Views/termsandconditions.aspx, read 2026-11-09): "
    "by using the site you accept its terms; the content 'should not be interpreted as a statement "
    "of law or used for any legal purposes'; doubts are to be checked with the department. No "
    "clause about automated access was found and the site has no robots.txt. One check is two "
    "requests to the public approved-project search; nothing is logged in or bypassed."
)

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
    "rera_andhra_pradesh": Source(
        key="rera_andhra_pradesh",
        title="AP RERA (Andhra Pradesh)",
        kind="rera",
        host="rera.ap.gov.in",
        terms_note=_APRERA_NOTE,
        demo=False,
        query_pattern=re.compile(r"[Pp][0-9]{11}", re.ASCII),
        query_hint="An AP RERA registration number is P followed by 11 digits, e.g. P12250106962.",
        path_template="",
        parser=parse_aprera_results,
        form=FormSpec(
            path="/RERA/Views/Reports/ApprovedProjectSearch.aspx",
            query_field="ctl00$ContentPlaceHolder1$txtName",
            submit=("ctl00$ContentPlaceHolder1$btnSubmit", "Search"),
            hidden_fields=(
                "__EVENTTARGET",
                "__EVENTARGUMENT",
                "__VIEWSTATE",
                "__VIEWSTATEGENERATOR",
                "__SCROLLPOSITIONX",
                "__SCROLLPOSITIONY",
                "__VIEWSTATEENCRYPTED",
                "__EVENTVALIDATION",
            ),
            required=("__VIEWSTATE", "__EVENTVALIDATION"),
        ),
        upper_case=True,
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
