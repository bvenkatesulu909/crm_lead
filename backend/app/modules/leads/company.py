"""The company behind a lead: website, industry and size (BP-02, ADR 0026 step EN1). Pure rules.

These three fields are filled by staff today and, from EN3 on, from suggestions the person reviews
(``company_details``). Their values are controlled so that a fact from outside can never put
arbitrary text into them:

* ``company_website`` - only ``https://<host>``: what staff type ("Example.com", "http://example.com/")
  is reduced to the lower-case host; a path, query, port, user info or an IP address is refused.
  The stricter rules for fetching a page (free-mail domains, internal names) live with the fetcher
  (ADR 0019 Amendment B), not here: a lead may record any real company site.
* ``company_industry`` - one key of :data:`INDUSTRIES`.
* ``company_size`` - one band of :data:`SIZES`.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

# Key -> label. The keys are stored; the labels are shown and copied to the account on conversion
# (an account's industry is free text). Order is the order of the pick list.
INDUSTRIES: dict[str, str] = {
    "agriculture": "Agriculture",
    "automotive": "Automotive",
    "banking_finance": "Banking and finance",
    "construction": "Construction",
    "consulting": "Consulting",
    "education": "Education",
    "energy": "Energy",
    "government": "Government",
    "healthcare": "Healthcare",
    "hospitality": "Hospitality",
    "information_technology": "Information technology",
    "insurance": "Insurance",
    "legal": "Legal",
    "logistics": "Logistics",
    "manufacturing": "Manufacturing",
    "media": "Media and entertainment",
    "non_profit": "Non-profit",
    "pharmaceuticals": "Pharmaceuticals",
    "real_estate": "Real estate",
    "retail": "Retail",
    "telecom": "Telecom",
    "textiles": "Textiles",
    "travel": "Travel and tourism",
    "wholesale": "Wholesale",
    "other": "Other",
}

# Employee bands. "1001+" is the open top band.
SIZES: tuple[str, ...] = ("1-10", "11-50", "51-200", "201-1000", "1001+")

WEBSITE_MAX = 255
# What the database accepts (and what normalise_website returns): https, a lower-case host of
# letters, digits, dots and hyphens (international names in their xn-- form), nothing after it.
WEBSITE_PATTERN = r"^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
_WEBSITE = re.compile(WEBSITE_PATTERN)


def normalise_website(value: str) -> str:
    """``https://host`` from what a person typed, or ``ValueError`` with a plain reason."""
    text = value.strip()
    if not text:
        raise ValueError("enter the company's website, e.g. example.com")
    if "://" not in text:
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise ValueError("enter only the website's address, e.g. example.com") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("the website must start with http:// or https://")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("enter only the website's address, e.g. example.com")
    if port is not None:
        raise ValueError("leave out the port number")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("enter only the website's address (no page or ? part), e.g. example.com")
    host = (parts.hostname or "").rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValueError("enter the website's name, not an IP address")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("this is not a valid website address") from exc
    website = f"https://{host}"
    if len(website) > WEBSITE_MAX or not _WEBSITE.fullmatch(website):
        raise ValueError("this is not a valid website address, e.g. example.com")
    return website


def industry_label(key: str | None) -> str | None:
    return INDUSTRIES.get(key) if key else None
