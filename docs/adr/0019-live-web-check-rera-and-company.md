# ADR 0019 — Live web check of a RERA number or a company (BP-15)

- **Status:** Accepted (2026-10-30) with the recommended answers to the five questions in section 5
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
| WC5 | BP-10 cases (injection text in a fake page, internal address refused, blocked source, off switch), `docs/webcheck.md`, Playwright journey, full runs |

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
