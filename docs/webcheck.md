# Web check of a RERA number or a company (BP-15, ADR 0019)

A salesperson can look up a RERA registration number or a company name on a public registry
from a lead or an account. The result is kept as **evidence** on that record, and the person who
asked gets a notification. This page explains how it works, how to try it, and what it will not do.

## What a person sees

On a lead or account page there is a **Web check** card:

1. Choose where to look (only sources that are switched on are offered) and type the RERA number or
   company name. The form tells you what a valid text looks like.
2. Press **Check**. The page says the check was queued. Nothing is fetched while you wait.
3. A moment later the worker fetches the page. The evidence appears on the card (newest first):
   found / not found / could not be read with certainty / could not be checked, the registered
   name, the status, the date it is valid until, where it looked, and when. A "What the page said"
   line shows the parsed fields as plain text.
4. You get a notification: "Web check finished for *name*: found".

If text from the page had to be cleaned (a link, a picture, hidden characters, text that reads like
an order to an AI), the card says so in words. The page itself is never linked from the card.

## Who may do what

| | Ask for a check | Read the evidence |
|---|---|---|
| Sales agent | their own leads and accounts | the same |
| Sales manager, tenant admin | every lead and account of the organisation | the same |
| Support agent | accounts (they read all accounts), not leads | the same |
| Customer (portal) | no | no |

Two rules apply to everyone, on top of the permission: you must be allowed to read the lead or
account (otherwise the answer is the same "not found" as for a record that does not exist), and
you may ask at most **10 checks per hour**; the organisation at most **200 per day**.

## The API

| | |
|---|---|
| `GET /api/v1/webcheck/sources` | the sources that are switched on (for the form) |
| `POST /api/v1/webcheck/checks` | `{target_type, target_id, source_key, query}` → `202 {request_id, status: "checking"}` |
| `GET /api/v1/webcheck/evidence?target_type=&target_id=` | the evidence of one lead or account, newest first |

Nothing else is accepted: no tenant, no person, no address. A source builds its own address; nobody
can hand the server a URL (ADR 0019, W1).

Error codes: `invalid_query` (422), `source_unavailable` (422), `invalid_target` (422),
`record_not_found` (404), `webcheck_limit_reached` (429), `webcheck_disabled` (503).

## How it is kept safe

- **A hardened fetcher** (`app/core/webfetch.py`) is the only code that fetches a page: https and
  port 443 only, only the source's own host, every resolved address must be public (no loopback,
  private, cloud-metadata ranges) and the connection goes to that checked address, robots.txt is
  honoured, redirects stay inside the host and are checked again, 10 seconds in total, 1 MB, no
  cookies, no compressed bodies, text content types only, one request a second per host.
- **No model reads a page.** Each source has a small parser. It says found / not found / unclear and
  never guesses (an unknown status, a repeated field, a wrong registration or an odd date is
  "unclear"). The excerpt is built from the parsed fields, never copied from the raw page.
- **Text from a page is cleaned** with the same screening as other untrusted text, and capped.
- **Evidence cannot be changed.** The database refuses every update and refuses to delete a row
  younger than 365 days (a trigger), and the application role has no update right. The worker
  deletes evidence older than that. Row-level security keeps every organisation's evidence apart.
- **Only a public identifier leaves the CRM:** the number or company name, never a person's data.
- **Switches:** `CRM_WEBCHECK_DISABLED` stops everything; a source works only when it is listed in
  `CRM_WEBCHECK_SOURCES` (or the demo sources are on).

## The organisation's switch and the assistant's tool

- **Switch.** The web check is an entry on the *AI agents* page (Automation) of the organisation, next
  to the four assistants. A tenant admin can switch it off; then nobody in the organisation can ask
  for a check and the API answers `webcheck_disabled`. The page shows how many checks were asked for
  this month. It has no token budget and no tools because it calls no language model.
- **The staff assistant's `check_rera` tool.** Arguments: `record_type` (lead or account),
  `record_id`, `source_key`, `query` - never an address. It queues a lookup **as the signed-in
  person** (so every rule above applies: permission, the record they may read, the switch, the
  limits) and tells the model only that the lookup is queued and that it must never state a result:
  the model sees no page. The assistant's instructions name the sources that are switched on so it
  can fill `source_key`. An organisation can take the tool away on the AI agents page like any other.

## Settings

| Setting | Meaning | Default |
|---|---|---|
| `CRM_WEBCHECK_DISABLED` | platform-wide kill switch | off |
| `CRM_WEBCHECK_SOURCES` | comma-separated source keys that are on | empty |
| `CRM_WEBCHECK_DEMO` | switch on the fictional demo sources (refused in production) | off |
| `CRM_WEBCHECK_PER_USER_HOUR` | checks one person may ask for per hour | 10 |
| `CRM_WEBCHECK_PER_TENANT_DAY` | checks one organisation may ask for per day | 200 |

## Trying it with the demo registry

The demo sources (`demo_rera`, `demo_company`) are a fictional registry served **inside the CRM**:
the real fetcher and parser run, only the network is replaced. It never contacts a real site.

1. In `backend\.env` add `CRM_WEBCHECK_DEMO=true`, restart the API and the worker.
2. Open a lead and use the Web check card with these numbers:

| Search text | Result |
|---|---|
| `DEMO/RERA/2026/001` | found, active, valid until 31 Mar 2028 (Lakeview Residency) |
| `DEMO/RERA/2026/002` | found, expired |
| `DEMO/RERA/2026/003` | found, revoked |
| `DEMO/RERA/2026/000` | not found |
| `DEMO/RERA/2026/777` | could not be read with certainty (the page shows another number) |
| `DEMO/RERA/2026/999` | could not be read with certainty (the page layout changed) |
| `DEMO/RERA/2026/666` | found, but the page tried to carry data out: it arrives cleaned and says so |
| company `Demo Builders Pvt Ltd` | found, active |
| company `Sunrise Homes` | could not be read with certainty (two companies with that name) |
| company `Ghost Constructions` | not found |

## Adding a real source (not done yet)

A real source is added only after the owner has read that site's terms of use and `robots.txt`
(ADR 0019, W2). It needs: its host, a query pattern, an address template, a parser with tests
against saved copies of the page's layout, and a `terms_note` that records what the terms say. It
is then switched on per deployment in `CRM_WEBCHECK_SOURCES`. Version 1 ships with demo sources only.

## Tests

- `tests/test_webfetch.py`, `tests/test_webfetch_transport.py` - the fetcher (fake network, and a
  local TLS server for the real transport).
- `tests/test_webcheck_rules.py` - queries, parsers and the demo registry (no database).
- `tests/db/test_webcheck.py` - requests, record-level denial, tenant isolation, limits, the worker
  job, the insert-only table and retention.
- `tests/db/test_webcheck_api.py` - the API and the notification.
- `frontend/src/lib/webcheck.test.tsx` - words, form and evidence list.
- `frontend/e2e/webcheck.spec.ts` - the journey in a real browser. Set `CRM_WEBCHECK_DEMO=true` for
  the API and the worker and `E2E_WEBCHECK_DEMO=1` for the test. The test agent asks for several
  checks per run, so set `CRM_WEBCHECK_PER_USER_HOUR=1000` as well when you run it more than once an
  hour (the real limit is 10 per person per hour). Like the other journeys that run the worker
  themselves it expects no standing worker.
