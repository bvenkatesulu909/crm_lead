# ADR 0026 — One-click company details on a lead (BP-02)

- **Status:** Accepted (2026-11-10) with the recommended answer to all six questions in section 6
- **Date:** 2026-11-10
- **Deciders:** Project owner
- **Depends on:** ADR 0019 (live web check: the safe fetcher, evidence, limits), ADR 0016 (agent
  registry: switch and limits), ADR 0017/0018 (cleaning untrusted text), ADR 0014 (approvals - not
  used here, see E4)

## 1. The problem

A salesperson gets a lead with a name, an e-mail address and a company name, and nothing else about
the company. Before calling they open the company's website by hand to learn what it does, how big it
is and where it is. BP-02 asks for a button on the lead that fills in **company website, industry and
size** from an outside source, with **every change shown before it is saved**.

What makes this an ADR: lead data could leave the CRM, and the CRM would fetch a page at an address
that comes from the lead's own data - ADR 0019 says nobody gives the fetcher an address.

## 2. What exists

- **Leads** have `company_name`, `email`, `phone`, `job_title`, `location` - no website, industry or
  size. **Accounts** have `website`, `industry`, `segment`.
- **The web check** (`app/core/webfetch.py`, `webcheck` module): https only, port 443, every resolved
  address must be public and the connection is pinned to it, robots.txt honoured, 10 s / 1 MB caps,
  text only, per-host rate limit, insert-only evidence kept 12 months, a switch in the agent
  registry, per-person and per-organisation limits, cleaned text, never a model reading the page.
- **Outside data services** (paid "enrichment" APIs) would need the person's e-mail address or name,
  an account, a contract and money. The real company registry (MCA) refuses automated clients;
  data.gov.in needs an API key - the owner deferred that (2026-11-09).

## 3. Decisions (proposed)

**E1 - v1 has one real source: the company's own public website.** The CRM reads the home page of the
company's site and, at most, its `/about` page. Nothing about the **person** leaves the CRM: no name,
no e-mail address, no phone - the only thing the outside world sees is an ordinary request for the
company's own public page. A paid enrichment service is **not** part of v1 (it would send personal
data to a third party; a separate decision with its own contract and DPDP review). A **demo source**
(fictional sites in the process, like ADR 0019's) is used by tests and evaluation.

**E2 - Where the address comes from, and the one change to ADR 0019.** The host is derived from the
lead's own data, in this order: a company website typed by staff on the lead, else the domain of the
lead's work e-mail address. It is accepted only when it is a plain registrable domain (no IP address,
no port, no path, no user info, no `localhost` / `.local` / `.internal`), not a free e-mail provider
(gmail.com, yahoo.com, outlook.com, … a fixed list), and not on a deny list; the fetch then goes
through the **same** fetcher with every protection of ADR 0019 (https, port 443, public addresses only
and pinned, robots.txt, caps, rate limits). This is the single place where an address is not fixed by
a source - written down as **ADR 0019 Amendment B**.

**E3 - Three new lead fields, controlled values.** `company_website` (https URL of the host, nothing
else), `company_industry` (one value from a fixed list of about 25 industries), `company_size`
(a band: 1-10, 11-50, 51-200, 201-1,000, 1,001+). A new migration with database checks. On
conversion they are copied to the account (`website`, `industry`) when the account's are empty.

**E4 - Suggestions, never silent changes; the person decides.** "Find company details" queues a job;
the worker fetches and a deterministic parser (no model) reads only structured facts: schema.org
`Organization` data in the page (name, `numberOfEmployees`, `address`), `og:site_name`, the meta
description and the title. Each field becomes a **suggestion with its evidence** (page, time, the
words it came from). The lead page shows old value, suggested value and source side by side; the
person ticks what to keep and saves - the normal lead update, with their own permissions, audited as
`lead.enriched` with the field names and the evidence id. No approval queue: a person reviews and
saves their own change (ADR 0014 is for changes an AI proposes).

**E5 - Never a guess.** A field is suggested only when the page states it in a structured way;
industry is matched from the page's own words to the fixed list and left empty when nothing matches
with confidence; size only from an employee number the page gives. "Nothing found" is an answer.
All page text is cleaned (`screen()`), capped and shown as plain text; it never reaches a model.

**E6 - Governed like the web check.** A registry entry `company_details` (no model; **off** until a
tenant administrator switches it on), limits per person per hour and per organisation per day,
evidence in the existing insert-only store for 12 months, and the same permission rules as reading
the lead (else 404).

## 4. What this does not do

No paid enrichment service, no LinkedIn or social profiles, no data about the person, no contact
details scraped from pages, no model reading pages, no automatic run on new leads (a person presses
the button), no change without the person saving it.

## 5. Steps (Phase EN), each stops for review

| Step | Content |
|---|---|
| EN0 | This ADR + ADR 0019 Amendment B (documents only) - **done 2026-11-10** |
| EN1 | Lead fields `company_website`, `company_industry`, `company_size` (migration, checks, schemas, lead form and page), copied to the account on conversion |
| EN2 | `company_site` source: host rules (E2) with the free-mail and deny lists, fetch through `webfetch`, deterministic parser, fictional demo sites; tests incl. SSRF attempts (IP literals, internal names, redirects to other hosts) |
| EN3 | API: request details (queues a job), list suggestions with evidence, apply chosen fields (normal lead update + audit); registry entry and limits |
| EN4 | "Company details" card on the lead page (suggestions side by side, tick and save) |
| EN5 | Evaluation cases (poisoned page, page without facts, free-mail lead, internal-address attempt), Playwright journey, docs |

## 6. Questions for the owner (recommended answer first)

1. **Sources in v1.** *Recommended:* the company's own website only (plus the demo source).
   Alternative: also a paid enrichment service now (sends personal data out; needs a contract).
2. **Fields.** *Recommended:* website, industry (fixed list) and size band. Alternative: also a short
   free-text company description.
3. **Who saves.** *Recommended:* the person who asked, after seeing each change. Alternative: through
   the approval queue (a manager approves every enrichment).
4. **Default.** *Recommended:* off until a tenant administrator switches it on. Alternative: on for
   every organisation.
5. **ADR 0019 Amendment B** (a host taken from the lead's website field or work e-mail, with the
   checks in E2). *Recommended:* yes. Alternative: only a website typed by staff, never the e-mail
   domain.
6. **Limits.** *Recommended:* 20 per person per hour, 300 per organisation per day. Alternative:
   your numbers.

## 7. Consequences

- Staff get the company basics with one click and see where each fact came from.
- The CRM makes one more kind of outbound request; its address comes from lead data, so the host
  rules (E2) and the fetcher's protections carry the weight - they get their own attack tests.
- Company websites seldom state their size in a structured way, so many leads will get only a
  website and an industry; that is the honest result of "never a guess".
