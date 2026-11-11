"""Company details from the company's own website (BP-02, ADR 0026 step EN2; ADR 0019 Amendment B).

Three parts, all without a database and without a model:

1. :func:`company_host` - which host a lead may lead to. Only from the lead itself (a website typed
   by staff, else the domain of the work e-mail address), and only a plain public name: no IP
   address in any spelling, no internal or reserved name, no free e-mail provider, nothing on the
   deny list. Everything else raises :class:`CompanyHostRefused` with a stable code.
2. :func:`parse_company_page` - structured facts only: schema.org ``Organization`` data
   (``name``, ``description``, ``numberOfEmployees``, ``address.addressLocality``),
   ``og:site_name``, the meta description and the title. Industry is matched from the page's own
   words to the fixed list and left empty unless one industry clearly wins; size only from an
   employee number the page gives. Every text is cleaned with ``screen()`` and capped. Never a
   guess.
3. :func:`lookup_company` - fetch the home page and ``/about`` through the unchanged safe fetcher
   (``app.core.webfetch.fetch``: https, port 443, public pinned addresses, robots.txt, caps,
   redirects only inside the host). A home page that redirects ``example.com`` to
   ``www.example.com`` is retried once at ``www.`` - a second candidate host, checked by the same
   rules, never a looser redirect rule.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Literal

from app.core.webfetch import (
    FetchPolicy,
    FetchRefused,
    FetchResult,
    HostLimiter,
    Resolver,
    Transport,
    fetch,
    looks_like_an_address,
    real_transport,
    system_resolver,
)
from app.modules.webcheck.rules import build_excerpt, clean_text, merge_codes

# --- 1. which host -----------------------------------------------------------------------------

# The demo company sites live under this suffix; it is only accepted when the demo is switched on
# (never in production - the service checks, as for the demo registry).
DEMO_SUFFIX = ".demo.example"

FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
        "rocketmail.com", "outlook.com", "outlook.in", "hotmail.com", "hotmail.co.in", "live.com",
        "live.in", "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me",
        "protonmail.com", "pm.me", "zoho.com", "zohomail.com", "zohomail.in", "rediffmail.com",
        "rediff.com", "gmx.com", "gmx.net", "mail.com", "yandex.com", "yandex.ru", "tutanota.com",
        "tuta.io", "fastmail.com", "hey.com", "inbox.com", "sify.com", "indiatimes.com",
    }
)  # fmt: skip

# Names that are never a company's public site (RFC 2606 / 6761 / 6762 and private habits).
INTERNAL_SUFFIXES = (
    ".localhost", ".local", ".internal", ".intranet", ".lan", ".home", ".corp", ".private",
    ".test", ".example", ".invalid", ".arpa", ".onion", ".localdomain", ".home.arpa",
)  # fmt: skip

# Our own systems and shared cloud endpoints: fetching them for "a lead's company" makes no sense
# and must never reach anything of ours.
DENIED_DOMAINS = (
    "crmlead.co.in", "googleapis.com", "amazonaws.com", "cloudfront.net", "azure.com",
    "windows.net", "netlify.app", "netlify.com", "github.io", "githubusercontent.com",
    "metadata.google.internal",
)  # fmt: skip

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
MAX_HOST = 253

HostCode = Literal[
    "no_source", "ip_literal", "internal_name", "bad_name", "free_mail", "denied"
]  # fmt: skip

HOST_MESSAGES: dict[str, str] = {
    "no_source": "Add the company's website, or a work e-mail address, to the lead first.",
    "ip_literal": "The website is an IP address; a company's name address is needed.",
    "internal_name": "That is not a public website.",
    "bad_name": "That is not a valid website name.",
    "free_mail": "The e-mail address is from a free mail service; add the company's website.",
    "denied": "That website cannot be checked.",
}


class CompanyHostRefused(Exception):
    """No host may be fetched for this lead. ``code`` is stable; the message is fixed (no input)."""

    def __init__(self, code: HostCode) -> None:
        self.code = code
        super().__init__(HOST_MESSAGES[code])


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def check_host(raw: str, *, demo: bool = False) -> str:
    """A host as it may be fetched, or :class:`CompanyHostRefused`. Lower case, IDNA (xn--) form."""
    text = raw.strip().rstrip(".").lower()
    if not text or "/" in text or "@" in text:  # a path, a user name or an e-mail address
        raise CompanyHostRefused("bad_name")
    if re.fullmatch(r"[^:\[\]]+:\d*", text):  # name:port
        raise CompanyHostRefused("bad_name")
    if looks_like_an_address(text):  # dotted, octal, hex, one big number, IPv6, [..]
        raise CompanyHostRefused("ip_literal")
    try:
        host = text.encode("idna").decode("ascii")
    except UnicodeError:
        raise CompanyHostRefused("bad_name") from None
    labels = host.split(".")
    if len(labels) < 2 or len(host) > MAX_HOST or not all(_LABEL.fullmatch(x) for x in labels):
        raise CompanyHostRefused("internal_name" if len(labels) < 2 else "bad_name")
    if labels[-1].isdigit():
        raise CompanyHostRefused("ip_literal")
    if demo and host.endswith(DEMO_SUFFIX):
        return host
    if host == "localhost" or any(host.endswith(s) for s in INTERNAL_SUFFIXES):
        raise CompanyHostRefused("internal_name")
    if any(_under(host, d) for d in DENIED_DOMAINS):
        raise CompanyHostRefused("denied")
    return host


def company_host(website: str | None, email: str | None, *, demo: bool = False) -> str:
    """The host for a lead: its website (stored as ``https://host``), else the domain of its
    work e-mail address."""
    if website and website.strip():
        text = website.strip()
        lowered = text.lower()
        for prefix in ("https://", "http://"):
            if lowered.startswith(prefix):
                text = text[len(prefix) :]
                break
        return check_host(text.rstrip("/"), demo=demo)
    if email and "@" in email:
        domain = email.rsplit("@", 1)[1].strip().rstrip(".").lower()
        if domain in FREE_MAIL_DOMAINS or any(_under(domain, d) for d in FREE_MAIL_DOMAINS):
            raise CompanyHostRefused("free_mail")
        return check_host(domain, demo=demo)
    raise CompanyHostRefused("no_source")


# --- 2. what a page says -----------------------------------------------------------------------

NAME_MAX = 200
DESCRIPTION_MAX = 300
LOCALITY_MAX = 100
MAX_JSON_LD_BYTES = 200_000
MAX_JSON_LD_BLOCKS = 10

SIZE_BANDS: tuple[tuple[int, int | None, str], ...] = (
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 1000, "201-1000"),
    (1001, None, "1001+"),
)

# Words that point at one industry of the lead's fixed list (app.modules.leads.company.INDUSTRIES).
# Kept short and specific; a page must mention at least two of them, and more than for any other
# industry, before an industry is suggested.
INDUSTRY_WORDS: dict[str, tuple[str, ...]] = {
    "real_estate": ("real estate", "apartments", "villas", "plots", "property", "properties",
                    "rera", "gated community", "residential projects", "developers"),
    "construction": ("construction", "contractor", "civil works", "infrastructure projects",
                     "builders", "turnkey"),
    "information_technology": ("software", "it services", "saas", "cloud", "digital solutions",
                               "app development", "technology services"),
    "banking_finance": ("bank", "banking", "finance", "loans", "nbfc", "investments", "wealth"),
    "insurance": ("insurance", "policyholders", "premium", "claims"),
    "healthcare": ("hospital", "clinic", "healthcare", "patients", "diagnostics", "medical"),
    "pharmaceuticals": ("pharmaceutical", "pharma", "formulations", "api manufacturing", "drugs"),
    "education": ("school", "college", "university", "students", "education", "courses"),
    "manufacturing": ("manufacturing", "manufacturer", "factory", "plant", "production"),
    "retail": ("retail", "store", "stores", "shop", "shopping", "e-commerce"),
    "hospitality": ("hotel", "resort", "restaurant", "hospitality", "banquet"),
    "logistics": ("logistics", "freight", "shipping", "warehousing", "supply chain", "courier"),
    "automotive": ("automotive", "automobile", "car dealer", "vehicles", "auto parts"),
    "energy": ("solar", "energy", "power", "renewable", "electricity"),
    "agriculture": ("agriculture", "farming", "farmers", "agri", "seeds", "crops"),
    "textiles": ("textile", "textiles", "garments", "fabrics", "apparel"),
    "travel": ("travel", "tours", "tourism", "holidays", "travel agency"),
    "telecom": ("telecom", "broadband", "mobile network", "connectivity"),
    "legal": ("law firm", "advocates", "legal services", "attorneys"),
    "consulting": ("consulting", "consultancy", "advisory", "consultants"),
    "media": ("media", "advertising", "film", "broadcast", "publishing"),
    "wholesale": ("wholesale", "distributor", "distribution", "traders"),
}  # fmt: skip
INDUSTRY_MIN_HITS = 2


@dataclass(frozen=True)
class PageFacts:
    """What one page states, already cleaned."""

    name: str | None = None
    description: str | None = None
    employees: int | None = None
    locality: str | None = None
    words_for_industry: str = ""
    cleaned: tuple[str, ...] = ()


class _Head(HTMLParser):
    """Title, a few meta tags and the JSON-LD blocks. Nothing else on the page is read."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_title = False
        self._in_json: list[str] | None = None
        self._json_bytes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").strip().lower()
            if key in ("description", "og:site_name", "og:description") and key not in self.meta:
                self.meta[key] = a.get("content", "")[:2000]
        elif tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            if len(self.json_ld) < MAX_JSON_LD_BLOCKS:
                self._in_json = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_json is not None:
            self.json_ld.append("".join(self._in_json))
            self._in_json = None

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 2000:
            self.title += data
        elif self._in_json is not None and self._json_bytes < MAX_JSON_LD_BYTES:
            self._json_bytes += len(data)
            self._in_json.append(data)


_ORG_TYPES = {"organization", "corporation", "localbusiness", "realestateagent", "company"}


def _organizations(node: Any, found: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 5 or len(found) >= 5:
        return
    if isinstance(node, list):
        for item in node[:20]:
            _organizations(item, found, depth + 1)
    elif isinstance(node, dict):
        kinds = node.get("@type")
        names = kinds if isinstance(kinds, list) else [kinds]
        if any(isinstance(k, str) and k.strip().lower() in _ORG_TYPES for k in names):
            found.append(node)
        if "@graph" in node:
            _organizations(node["@graph"], found, depth + 1)


def _employees(value: Any) -> int | None:
    """A whole, plausible employee number - or None. A range uses its upper end."""
    if isinstance(value, dict):
        value = value.get("value", value.get("maxValue"))
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"\s*\d{1,7}\s*", value):
        number = int(value)
    else:
        return None
    return number if 1 <= number <= 5_000_000 else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def parse_company_page(body: bytes) -> PageFacts:
    """Read one HTML page. A page that cannot be read gives empty facts, never an exception."""
    head = _Head()
    try:
        head.feed(body.decode("utf-8", errors="replace"))
        head.close()
    except Exception:  # noqa: BLE001 - a broken page is "nothing found", not a crash
        return PageFacts()
    org: dict[str, Any] = {}
    for block in head.json_ld:
        try:
            data = json.loads(block)
        except (ValueError, RecursionError):
            continue
        found: list[dict[str, Any]] = []
        _organizations(data, found)
        if found:
            org = found[0]
            break
    address = org.get("address") if isinstance(org.get("address"), dict) else {}
    raw_name = _text(org.get("name")) or _text(head.meta.get("og:site_name")) or _text(head.title)
    raw_description = (
        _text(org.get("description"))
        or _text(head.meta.get("description"))
        or _text(head.meta.get("og:description"))
    )
    raw_locality = _text(address.get("addressLocality")) if address else None
    codes: list[list[str]] = []

    def clean(value: str | None, cap: int) -> str | None:
        if value is None:
            return None
        text, found_codes = clean_text(value, cap)
        codes.append(found_codes)
        return text or None

    name = clean(raw_name, NAME_MAX)
    description = clean(raw_description, DESCRIPTION_MAX)
    locality = clean(raw_locality, LOCALITY_MAX)
    words = " ".join(x for x in (name, description, clean(head.title or None, NAME_MAX)) if x)
    return PageFacts(
        name=name,
        description=description,
        employees=_employees(org.get("numberOfEmployees")),
        locality=locality,
        words_for_industry=words.lower(),
        cleaned=merge_codes(*codes),
    )


def size_band(employees: int | None) -> str | None:
    if employees is None:
        return None
    for low, high, band in SIZE_BANDS:
        if employees >= low and (high is None or employees <= high):
            return band
    return None


def industry_from_words(text: str) -> str | None:
    """One industry key when the page clearly points at it, else None (never a guess)."""
    if not text:
        return None
    padded = f" {re.sub(r'[^a-z0-9]+', ' ', text.lower())} "
    hits: dict[str, int] = {}
    for key, words in INDUSTRY_WORDS.items():
        count = sum(1 for w in words if f" {w} " in padded)
        if count:
            hits[key] = count
    if not hits:
        return None
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    best, best_hits = ranked[0]
    if best_hits < INDUSTRY_MIN_HITS:
        return None
    if len(ranked) > 1 and ranked[1][1] == best_hits:
        return None
    return best


# --- 3. the lookup -----------------------------------------------------------------------------

Verdict = Literal["found", "not_found", "unclear"]


@dataclass(frozen=True)
class CompanyLookup:
    """The suggestions for one lead, with what they rest on. ``website`` is the site that answered
    (``https://host``); ``excerpt`` is built from parsed fields, never copied from the raw page."""

    verdict: Verdict
    host: str
    website: str | None = None
    industry: str | None = None
    size: str | None = None
    name: str | None = None
    description: str | None = None
    locality: str | None = None
    pages: tuple[str, ...] = ()
    excerpt: str = ""
    cleaned: tuple[str, ...] = ()
    refusal: str | None = None  # the fetcher's code when nothing could be read
    notes: tuple[str, ...] = field(default=())


def _get(
    url: str, host: str, resolver: Resolver, transport: Transport,
    policy: FetchPolicy, limiter: HostLimiter | None,
) -> FetchResult:  # fmt: skip
    return fetch(url, host=host, resolver=resolver, transport=transport, policy=policy,
                 limiter=limiter)  # fmt: skip


def lookup_company(
    host: str,
    *,
    resolver: Resolver = system_resolver,
    transport: Transport = real_transport,
    policy: FetchPolicy = FetchPolicy(content_types=("text/html",)),  # noqa: B008 - frozen
    limiter: HostLimiter | None = None,
) -> CompanyLookup:
    """Read the home page (and ``/about``) of ``host``, which :func:`company_host` has checked.

    Raises nothing for a site that refuses, fails or says nothing: the answer is ``unclear`` (could
    not be read) or ``not_found`` (read, but no fact to suggest), with the fetcher's code."""
    candidates = [host] if host.startswith("www.") else [host, f"www.{host}"]
    home: FetchResult | None = None
    used = host
    refusal: str | None = None
    for candidate in candidates:
        try:
            home = _get(f"https://{candidate}/", candidate, resolver, transport, policy, limiter)
            used = candidate
            break
        except FetchRefused as exc:
            # The first reason is the one that explains the result ("it redirected elsewhere"),
            # not the www. retry's ("no such name").
            refusal = refusal or exc.code
            # Only "it redirected to another name" earns the www. retry; anything else is final.
            if exc.code != "bad_host":
                break
    if home is None or home.status != 200:
        return CompanyLookup(
            "unclear", host, refusal=refusal or f"status_{home.status if home else 0}"
        )
    facts = [parse_company_page(home.body)]
    pages = [home.final_url]
    try:
        about = _get(f"https://{used}/about", used, resolver, transport, policy, limiter)
        if about.status == 200:
            facts.append(parse_company_page(about.body))
            pages.append(about.final_url)
    except FetchRefused:
        pass  # the home page is enough; /about is a bonus
    name = next((f.name for f in facts if f.name), None)
    description = next((f.description for f in facts if f.description), None)
    locality = next((f.locality for f in facts if f.locality), None)
    employees = next((f.employees for f in facts if f.employees is not None), None)
    industry = industry_from_words(" ".join(f.words_for_industry for f in facts))
    size = size_band(employees)
    website = f"https://{used}"
    excerpt = build_excerpt(
        [
            (label, value)
            for label, value in (
                ("Name", name),
                ("Description", description),
                ("Place", locality),
                ("Employees", str(employees) if employees is not None else None),
            )
            if value
        ]  # fmt: skip
    )
    verdict: Verdict = "found" if (industry or size) else "not_found"
    return CompanyLookup(
        verdict=verdict,
        host=used,
        website=website,
        industry=industry,
        size=size,
        name=name,
        description=description,
        locality=locality,
        pages=tuple(pages),
        excerpt=excerpt,
        cleaned=merge_codes(*(list(f.cleaned) for f in facts)),
    )
