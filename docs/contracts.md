# Contracts and renewals (design, 2026-10-23)

**Status: C1 (database), C2 (API), C3 (worker) and C4 (screens) built.** Contact, deal and quote links are supported by the API but not yet offered on the form (a later small step).
Branch `feat/contracts`. Written before the code because the plan had no spec for this module.

## What it is for

A sales rep or manager records the **contract** a customer account has signed: what it covers, for
how long, for how much, and what happens at the end. The CRM then keeps track of the dates so that
nobody forgets a renewal: it reminds the owner before the contract ends, and it shows which
contracts are about to expire or have expired.

Out of scope for now: e-signature, clause libraries and templates, automatic invoicing from a
contract, and a customer-portal view (the portal can follow later, like quotes did).

## Words

- **Contract:** one agreement with one customer account.
- **Renewal date:** `end_date` minus `renewal_notice_days`. From this day the owner is reminded.
- **Renewal:** a new draft contract linked to the old one (`renewed_from_id`); the old contract
  becomes `renewed` once the new one is activated.

## Data (migration 0037)

Every table has `tenant_id`, forced row-level security and a tenant policy (ADR 0009; the guard
test `test_rls_tenant_tables.py` fails any tenant table without it).

| Table | Purpose | Key columns |
|---|---|---|
| `contracts` | the agreement | `number` (per tenant, shown as CT-0001), `title`, `account_id`, `contact_id?`, `owner_id`, `quote_id?`, `opportunity_id?`, `status`, `start_date`, `end_date`, `auto_renew`, `renewal_notice_days`, `renewal_term_months?`, `currency`, `total_value`, `billing_frequency`, `terms?`, `renewed_from_id?`, `terminated_at?`, `termination_reason?`, `renewal_reminded_at?`, `version` |
| `contract_events` | history of status changes and notes, **insert-only** for the app | `contract_id`, `event_type`, `from_status`, `to_status`, `note`, `actor_user_id`, `created_at` |
| `contract_number_counters` | gapless-enough numbering per organisation | `tenant_id`, `last_number` |

Database rules (CHECK constraints, so a bug in the app cannot store nonsense):
- `status` is one of `draft`, `active`, `expired`, `terminated`, `renewed`.
- `end_date >= start_date`; `total_value >= 0`; `currency` is three capital letters.
- `renewal_notice_days` is 0 to 365; `renewal_term_months` is empty or 1 to 120.
- A contract that is `terminated` has a `terminated_at` and a reason; others have neither.
- Account, contact, owner, quote and opportunity references are tenant-scoped composite foreign
  keys, so a contract can never point at another organisation's record.
- Money is `NUMERIC(18,2)`, never a float.

## Status flow (rules live in `rules.py`, pure and unit-tested)

```
draft ──activate──► active ──terminate──► terminated
                      │  ├─ end date passes, not auto-renew ──► expired
                      │  └─ renew (new draft linked back) ──► renewed  (when the new one is activated)
```

- Only `draft` contracts can be edited freely; active ones can change owner, notice days, terms
  notes and auto-renew, but not account, dates or value (a change of those is a renewal).
- `activate`, `terminate` and `renew` are manager actions (`contract:manage`); agents create and edit.
- `activate` needs a start and an end date, and the end date must not be in the past.
- `terminate` needs a reason and only works on an active contract.
- The worker (about once a minute, safe to repeat), for each organisation:
  - marks `active` contracts past `end_date` as `expired` and publishes `contract.expired`;
    with `auto_renew` it also prepares the renewal as a **draft** (never activated by itself:
    the terms or the price may have to change first);
  - once the renewal date is reached (end date minus `renewal_notice_days`) it writes a
    `renewal_reminder` entry to the history and publishes `contract.renewal_due` **once**.
    Changing the end date or the notice days re-arms the reminder.
  The owner and creator are notified (the reminder also by e-mail, by default), each only if
  they may see the contract. The worker's history entries have no person; there is no audit row
  for them, as with the quote jobs.

## Who may do what (permissions, step C1 registers them)

| Permission | Meaning | Roles |
|---|---|---|
| `contract:read:all` / `contract:read:own` | see all contracts / those you own or on accounts you own | managers and admins / sales agents |
| `contract:write:all` / `contract:write:own` | create and edit drafts, log notes | same |
| `contract:manage` | activate, terminate, renew | managers and tenant admins |

Support agents get no contract access in the first version. Customers (portal) get none until a
portal view is added. Record-level rules reuse the pattern of quotes: "own" means owned by the
user or on an account the user owns. Lists are filtered in SQL. A contract the user may not see
answers 404, never 403.

## Steps

| Step | Content | State |
|---|---|---|
| **C1** | this design; migration 0037 (3 tables, RLS, insert-only history); SQLAlchemy models; permissions registered; guard tests | built |
| C2 | `rules.py`, schemas (separate input schemas, no server fields), repository, policies, service, router `/api/v1/contracts`, audit and domain events, 64 tests (happy path, validation, tenant isolation, role denial, record denial, ID tampering, version conflicts, filters, audit) | built |
| C3 | worker: expiry sweep, auto-renew draft and renewal reminders (notification to the owner and creator, e-mail for reminders; a workflow rule can add a task) | built |
| C4 | screens: list with filters, detail with history, create/edit, activate/terminate/renew, a card on the account page, "Contracts" tile available in the module grid; Playwright journey; this document completed | built |

## Tests required before C2 is called done

Happy path, validation, tenant isolation (another organisation's contract is invisible and
cannot be referenced), role denial (support agent, customer), record-level denial (an agent
sees only own), ID tampering (account of another organisation, foreign `owner_id`), status-flow
rules (every illegal transition refused), insert-only history, RLS guard.

## The API (step C2)

All under `/api/v1/contracts`, staff only; every call is checked twice (RBAC permission, then the
record-level policy in SQL). A contract the user may not see is a 404.

| Call | Who | What |
|---|---|---|
| `GET /contracts` | readers | list; filters `q` (title or CT-0001), `status` (repeatable), `account_id`, `owner_id`, `ending_within_days`; paging |
| `POST /contracts` | writers | create a draft; account, contact, deal and quote must belong together and be visible |
| `GET /contracts/{id}` and `/history` | readers | one contract (with `renewed_to_id`), its events newest first |
| `PATCH /contracts/{id}` | writers | draft: any business field; active: owner, title, contact, auto-renew, notice, renewal term, terms |
| `POST /contracts/{id}/notes` | writers | add a note to the history |
| `POST /contracts/{id}/activate` | managers | draft becomes active; a renewal marks the old contract "renewed" |
| `POST /contracts/{id}/terminate` | managers | needs a `reason`; active contracts only |
| `POST /contracts/{id}/renew` | managers | creates a linked draft (dates and value default from the old one); one renewal at a time |

Changes carry the `version` the client saw; a stale version answers 409 `version_conflict`.
Error codes: `contract_not_found` (404), `related_not_found` (404), `invalid_contract` (422),
`contract_state` (409), `version_conflict` (409).

## The screens (step C4)

| Screen | What it does |
|---|---|
| `/contracts` | Table with the status, value, end date and an "Ends in N days" hint (amber inside 30 days, red once past); filters: search (title or CT-0007), status, ending within 30/60/90 days; "New contract" for people who may write |
| `/contracts/new` | Form for a draft. The account is chosen with the type-to-search field (works with any number of accounts); "New contract" on an account page pre-selects it |
| `/contracts/[id]` | Details (account, owner, period, value, renewal reminder, links to the previous and the following contract), terms, history with who and when ("The system" for worker entries) and the action buttons |
| `/contracts/[id]/edit` | A draft shows every field; an active contract shows only the title, renewal settings and terms, with a note that dates and value change by renewing |
| Account page | A "Contracts" card (latest 10, "All N contracts") |

The buttons follow the permissions (agents: edit and note; managers: also activate, renew,
terminate) and the status (a renewal can be made once; terminated and renewed contracts are
final). This is **display only**: the API checks permissions, versions and the status flow on
every call. The sidebar entry and the "Contracts & Renewals" tile appear only for people who
may read contracts (sales agents, managers, tenant admins - not support or customers).

Tests: 33 component tests (labels, the end-of-contract hint, form validation against the API's
limits, menu visibility, which buttons show in each state) and 3 Playwright journeys (draft ->
activated -> renewed -> the renewal replaces it; terminate with a reason; filters and
visibility for other agents and support).
