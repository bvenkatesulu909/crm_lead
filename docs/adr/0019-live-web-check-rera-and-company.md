# ADR 0019 — Live web check of a RERA number or a company (BP-15)

- **Status:** Accepted (2026-10-30) with the recommended answers to the five questions in section 5;
  **Amendment A** (section 7, form search for AP RERA) accepted 2026-11-09 with the four recommended answers
- **Date:** 2026-10-30
- **Deciders:** Project owner
- **Depends on:** ADR 0005 (outbox and worker), ADR 0014 (approval queue), ADR 0016 (agent
  registry and budgets), ADR 0017/0018 (screening of untrusted text)

## 1. The problem

A salesperson wants to know whether a RERA registration number (the Indian real-estate regulator's
project / agent number) or a company is real and in good standing before spending time on a lead or
a deal. Today they open the regulator's or the registry's website by hand and paste what they find
into a note. We would like the CRM to do the lookup and keep **evidence**: what was asked, where, when,
what came back.

This is the first feature that makes the **backend call out to the open internet** on behalf of a
user. That brings four new risks that nothing built so far covers:

1. **Data leaves.** Whatever we put in the request is seen by a third party.
2. **SSRF** (server-side request forgery): if the address comes from a user or a model, someone can
   make our server fetch an internal address (the database, the file store, a cloud metadata
   service) and read the answer.
3. **Untrusted content comes in.** A web page is text written by someone else. If a model reads it,
   it is an indirect prompt injection (the reverse of ForcedLeak). Even without a model, the text is
   shown to staff.
4. **Rules of the sites.** A public registry may forbid automated access or limit it; breaking that
   is a legal and reputational problem, not a technical one.

## 2. Decisions

**W1 — No free browsing. The model and the user never give an address.** A check names a **source**
(a key from a fixed catalogue, e.g. `rera_telangana`, `mca_company`) and a **query** (a RERA number,
or a company's legal name). The server builds the address from the source's template. Consequence:
the no-fetch rule of ADR 0018 (no tool argument is an address) stays true, and a poisoned record
cannot steer the fetch anywhere.

**W2 — The catalogue is empty until the owner fills it.** Each source records its address template,
what it returns, its parser, a `terms_note` (what its terms of use say about automated access) and
whether `robots.txt` allows the path. A source is **off by default** and is switched on per
deployment by the owner (`CRM_WEBCHECK_SOURCES`), after the owner has read that site's terms. v1 is
built and tested against a **fake source** only; the first real source is a separate step.

**W3 — A hardened fetcher in `app/core`, with its own tests.** One function is allowed to touch the
internet, and it refuses by default:
- `https` only; port 443 only; the host must equal the source's host (no redirect to another host);
- the host name is resolved by us, **every** address must be public (no loopback, private,
  link-local, multicast, or cloud-metadata ranges, IPv4 and IPv6) and the connection is made to
  *that* address (so a second DNS answer cannot swap it);
- time limit 10 s, size limit 1 MB, no cookies, no credentials, content types HTML / JSON / plain
  text only, a fixed `User-Agent` that names the CRM and gives a contact;
- `robots.txt` honoured, at most one request per second per host, and a per-source daily ceiling.

**W4 — Deterministic parsers; no model reads a page (v1).** Each source has a small parser that
turns the response into a fixed record: `found | not_found | unclear`, the registered name, the status
and an expiry date when the page says so. If the layout changed and the parser cannot be sure, the
answer is `unclear`, never a guess. The staff assistant receives only that structured record. Letting
a model summarise pages is a different risk and would need its own ADR.

**W5 — Evidence is stored, insert-only, and cleaned.** A table `web_evidence` (tenant, the lead or
account it is about, source, query, who asked, when, HTTP status, final address, SHA-256 of the body,
the parsed record, and an **excerpt** of at most 4 KB). The excerpt goes through the same screening as
other untrusted text (`screen()`: hidden characters, markup, images and links out) and is shown as
plain text. Forced RLS, rows cannot be updated or deleted by the application; a worker job deletes
evidence after a retention period.

**W6 — It runs in the worker, not inside the request.** A request creates a job (`webcheck.run`,
ADR 0005) and returns "checking". The result arrives as evidence and a notification to the asker. A
site that is slow or down costs a retry, not a stuck page.

**W7 — Only a public identifier leaves.** The query is checked against a pattern (a RERA number's
shape, a company name's length and characters). A lead's person data (name, phone, e-mail, budget)
is **never** part of a request. The audit entry `webcheck.requested` records source and query.

**W8 — Who and how much.** Staff who may read the lead or account can ask; at most 10 checks per person
per hour and 200 per organisation per day (settings, like the other limits). A change to a record
based on the result (for example "mark the RERA number as verified") is **not** done by the check:
it would go through the approval queue (ADR 0014) as a new action kind, in a later step.

**W9 — Switches.** A platform switch `CRM_WEBCHECK_DISABLED` and a per-organisation switch. The
per-organisation switch lives in the agent registry (ADR 0016) as a fifth catalogue entry that uses no
model: it appears on the same page, counts checks instead of tokens, and the staff assistant's
`check_rera` tool is subject to it (and to the assistant's own switch).

## 3. What this does not do

- It does not browse, crawl or search the web, and it does not follow links.
- It does not log in anywhere, solve CAPTCHAs, or work around a site that blocks automation. A
  blocked or refused request is stored as `error` evidence and not retried more than a few times.
- It does not send any person's data.
- It does not change a lead or an account.

## 4. Steps (Phase WC), each stops for review

| Step | Content |
|---|---|
| WC0 | This ADR + the phase plan (documents only) |
| WC1 | `app/core/webfetch.py`: the hardened fetcher, tested without a network (fake resolver and transport): every refused address range, redirect, size, time, content type, robots |
| WC2 | Module `webcheck`: migration 0045 (`web_evidence`, forced RLS, insert-only), source catalogue with the fake source, parsers, service, worker job, API, audit, events, retention job |
| WC3 | Registry entry (no model), staff assistant tool `check_rera` (arguments: source key and query only), limits |
| WC4 | Screens: "Check" button and an Evidence card on lead and account pages, plain-text excerpts, notification |
| WC5 | BP-10 cases (injection text in a fake page, internal address refused, blocked source, off switch), `docs/webcheck.md`, Playwright journey, full runs - done 2026-11-08 |

## 5. Questions for the owner

1. **Sources.** Build against a fake source only and add the first real one (which state's RERA
   portal, which company registry) in a later step, after you have read its terms? *Recommended: yes.*
2. **No model reads pages in v1** (parsers only)? *Recommended: yes.*
3. **Who may ask:** every staff member who can read the record, 10 per hour; managers and admins can
   read all evidence of the organisation. *Recommended.*
4. **Switch:** a fifth entry in the agent registry (counts checks, not tokens). *Recommended.*
5. **Retention:** delete evidence after 12 months. *Recommended.*

## 6. Consequences

- The backend host needs outbound HTTPS in production; nothing else about hosting changes.
- A legal reading of each source's terms becomes a gate before any real source is enabled, and it is
  yours, not the code's.
- The fetcher becomes the only code that fetches a web page for a user. (The AI providers are already
  called over the internet, by their own clients with fixed addresses; those stay as they are.) A test
  in WC1 will fail if another module starts fetching pages with its own HTTP client.

## 7. Amendment A (2026-11-09) - a narrow form search, for the first real source (AP RERA)

- **Status:** Accepted 2026-11-09 with the four recommended answers in 7.5 (the owner reads the AP RERA
  terms before the source is switched on anywhere).
- **Why now:** the pilot client is in Anantapuramu, Andhra Pradesh, so the first real source should be
  the AP RERA portal. Its search is an old ASP.NET form: it must be POSTed back with the page's own
  hidden state. The fetcher of W3 sends only GET requests, so it cannot use this site.

### 7.1 What was found (manual research, 2026-11-09, a handful of requests by hand)

| Point | Finding |
|---|---|
| Site | `https://rera.ap.gov.in`, search page `/RERA/Views/Reports/ApprovedProjectSearch.aspx` |
| robots.txt | none (404) - under RFC 9309 that means no rules; the fetcher already reads it so |
| Terms of use | `termsandconditions.aspx`: by using the site you accept its terms; the content "should not be interpreted as a statement of law or used for any legal purposes"; doubts are to be checked with the department; no clause about automated access was found. The owner reads the page before deciding (W2) - this table is not legal advice |
| CAPTCHA | none on the project search (one appears only in the login pop-up, which we never use) |
| How the search works | GET the page (about 117 KB) -> it carries hidden fields `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` and a few empty ones -> POST them back to the same path with the keyword box filled and the Search button named (about 1 KB) -> the answer is the same page with a results table |
| Cookies | the site sets `ASP.NET_SessionId`, but the search works **without** sending it back - W3's "no cookies" can stay |
| What a result row holds | S.No., Application No, **Registration No**, Project Name, Promoter Name, Place, Status |
| Registration numbers | look like `P` + 11 digits, e.g. `P12250106962`; a search for one returns its row |
| Sizes | both answers well under the 1 MB limit (time per request to be measured in WC6c) |

### 7.2 Decisions

**W7 - One more fetch shape: "form search", and nothing wider.** A source may declare
`kind = "form_search"` instead of an address template. Then a check makes exactly **two** requests:

1. `GET https://<host><path>` - the source's fixed host and path;
2. `POST https://<host><path>` - **the same host and the same path**, body
   `application/x-www-form-urlencoded`, made only of:
   - the hidden fields **the page itself sent** whose names are on the source's allow-list
     (for AP RERA: `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, `__EVENTTARGET`,
     `__EVENTARGUMENT`, `__VIEWSTATEENCRYPTED`, `__SCROLLPOSITIONX`, `__SCROLLPOSITIONY`), copied as
     they came, each at most 64 KB, all together at most 128 KB;
   - **one** query field (its name fixed in the source) holding the already-validated query;
   - the submit button's fixed name and value from the source.

Nothing else can be added: no field from a person or a model, no other page, no file, no header but
the content type. The query must still match the source's pattern (W1) before anything is sent.

**W8 - Every W3 protection applies to both requests, unchanged.** HTTPS and port 443 only; the
host resolved by us, every address public, the connection pinned to it; robots.txt read first and
obeyed for that path; **no redirect** on the POST (a redirect there is treated as an error, not
followed); 10 s for the whole check (both requests together); 1 MB per answer; no cookies; the fixed
`User-Agent` with a contact; HTML only. The per-host limiter counts **every request** (robots.txt,
the page and the answer - at least one second apart, and against the per-host daily ceiling); the
per-person and per-organisation limits of the web check still count **checks**.

**W9 - Fail closed when the form changes.** If the page has no form with that path, a required hidden
field is missing, a field is too large, or the answer has no results table with the expected column
headings, the check ends as `unclear` or `error` - never a guess - exactly like a layout change in
W4. The parser reads only the results table and keeps only the row whose Registration No equals the
query exactly (both upper-cased; one row or none).

**W10 - The AP RERA source.** Key `rera_andhra_pradesh`, label "AP RERA (Andhra Pradesh)", host
`rera.ap.gov.in`, query pattern `^P\d{11}$` (case-insensitive, stored upper-case), parser to
`found` (status, project name, promoter, place, registration number) / `not_found` / `unclear`, and a
`terms_note` that quotes the "not for legal purposes" line. The evidence card and the assistant keep
saying what W5 already says: this is what the registry's public page showed at that time, not a legal
opinion. **Off by default**; switched on per deployment in `CRM_WEBCHECK_SOURCES` only after the
owner's yes (W2).

**W11 - The company registry stays on the demo source.** The national company registry (MCA) is
believed to put its company search behind a CAPTCHA (not tested here). Section 3 already rules out
solving CAPTCHAs, so no real company source is planned in this amendment.

### 7.3 What this amendment does not change

The no-address rule (W1 / ADR 0018), no model reading pages (W4), insert-only cleaned evidence (W5),
who may ask and the limits, the agent registry switch, retention and section 3 all stay as they are.
The guard test that fails when another module fetches pages keeps holding: the form search lives
inside `app/core/webfetch.py`.

### 7.4 Steps (each stops for review)

| Step | Content |
|---|---|
| WC6a | `webfetch`: the form-search shape (W7-W9), tested without a network: same host/path only, allow-listed hidden fields only, size caps, POST redirect refused, robots, limiter counts every request, one deadline for the check; deliberate breaks of each protection must fail a test - **done 2026-11-09** (`form_search`, `FormSpec`, `build_form`; 41 + 2 new tests, 17 of 17 breaks caught) |
| WC6b | Source `rera_andhra_pradesh`: parser tested against **saved copies** of the real page (a found row, no row, a changed layout, a page with injected text), `terms_note`, docs; no network in CI - **done 2026-11-09**: the fixtures copy the real page's structure with invented content (no real project data in the public repository); new status `registered` |
| WC6c | One live check from the development PC against the real site (with the owner's yes), then the owner decides whether to switch it on for staging; a BP-10 case on the saved copy - **live check done 2026-11-09** with the real code path (real resolver and TLS transport, a shared limiter): a public registration number -> found / registered, a made-up one -> not found; three requests per check (robots.txt, page, POST) about 3 s each including the 1 s spacing; the search answers without the page's sorting fields (the allow-list is enough). Switching it on for staging and the BP-10 case are still open |

### 7.5 Questions for the owner

1. **Allow the form-search shape (W7-W9)** - two requests to the same page, nothing added but the
   query? *Recommended: yes.*
2. **AP RERA as the first real source (W10)**, after you have read
   `https://rera.ap.gov.in/RERA/Views/termsandconditions.aspx` yourself? *Recommended: yes.*
3. **Leave the company check on the demo source (W11)?** *Recommended: yes.*
4. **The live test in WC6c:** a few real searches from your PC, with registration numbers you choose
   (public data), before anything runs on the server? *Recommended: yes.*
