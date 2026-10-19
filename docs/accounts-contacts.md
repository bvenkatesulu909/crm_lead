# Customer accounts and contacts (Phase B)

This phase adds full account management, a contacts module, a 360° customer page and logging of lead activities.
Everything is stored in PostgreSQL. Nothing on these screens is mock data.

## What you can do

| Area | Screens | Who |
|---|---|---|
| **Accounts** | `/accounts` (search, status, segment; *Archived* tab for managers) · `/accounts/new` · `/accounts/{id}` (360°) · `/accounts/{id}/edit` | Agents: their own accounts. Managers/admins: all. Support: read only. |
| **Contacts** | `/contacts` (search, consent filter) · `/contacts/new` · `/contacts/{id}` (details + change history) · `/contacts/{id}/edit` | Agents: contacts they own and the people at their accounts. Managers/admins: all. Support: read only. |
| **Lead activities** | "Log activity" on `/leads/{id}`: call, meeting, e-mail or note, optionally back-dated | Whoever may change the lead |

### Account rules
- **Owner.** Sales staff become the owner of what they create. Only managers and admins can choose another owner or change it later. The owner must be an active sales employee of the same organisation.
- **Hierarchy.** An account can have a parent account (group or head office), up to 10 levels deep.
  - Loops are refused, for example making an account its own grandparent.
  - The 360° page shows both the parent and the child accounts.
- **Segment.** Enterprise, mid-market, small business, public sector or non-profit. This is a fixed list for now; organisation-defined lists come with the administration phase.
- **Preferred contact channel.** E-mail, phone, mobile, post, or "no contact".
- **Deactivate and reactivate.** Any user who may change the account can do this, with an optional reason.
- **Archive and restore** (managers and admins only):
  - The account must be inactive first, and must have no live child accounts.
  - Archived accounts disappear from every list. Nothing is deleted.
  - A child can only be restored after its parent.
- **Account numbers** are unique within the organisation, including archived accounts.
- **Concurrent edits.** Every change needs the version the user last saw. An edit made by someone else in the meantime gives "changed by someone else" (409).

### Contact rules
- **Linking to an account.** A contact can only be linked to an account the user can see. Any other account answers **404**, exactly as if it did not exist.
- **Primary contact.** There is at most **one primary contact per account**, enforced by a unique index in the database.
  - Making someone primary removes the flag from the previous primary contact, and both changes are recorded.
  - Moving a contact to another account removes its primary flag.
- **E-mail consent:** "Not asked yet", "Agreed to e-mails" or "Opted out".
  - The server records the date of every change itself; clients cannot send or back-date it.
- **Do not call** is a separate flag.
- **Archiving a contact** hides it everywhere and keeps its history.

### The 360° account page
The page shows, all from real records the user may see:
- profile;
- contacts, with primary badge, consent and do-not-call;
- company hierarchy;
- opportunities (read-only list);
- orders, invoices, support tickets and converted leads;
- portal access;
- a **relationship timeline**.

The timeline merges account and contact changes from the audit log with orders, invoices, tickets and lead conversions, newest first.

## Not in this phase (shown honestly on the screens)

| Requested | Status |
|---|---|
| Customer team | Teams don't exist yet (Phase C). The profile says so. |
| Logging calls and meetings with a **contact** | Comes with Activities and tasks (Phase D). Logging on **leads** works now. |
| Contract history | No contracts module yet. Purchase history = orders and invoices. |
| Opportunity editing and pipeline board | Phase D. Today opportunities are listed read-only (`GET /opportunities`). |

## API (see `docs/api/openapi.json`)

| Method | Path | Notes |
|---|---|---|
| GET | `/accounts` | New filters: `segment`, `owner_id`, `parent_account_id`, `archived=true` (managers only). |
| POST | `/accounts` | Create an account. |
| PATCH | `/accounts/{id}` | Edit the account; requires `version`. |
| POST | `/accounts/{id}/status` | Deactivate or reactivate. |
| POST | `/accounts/{id}/archive` | Managers only. |
| POST | `/accounts/{id}/restore` | Managers only. |
| GET | `/accounts/{id}/timeline` | Account history from the audit log. |
| GET | `/contacts` | Filters: `q`, `account_id`, `owner_id`, `email_consent`, `primary_only`, `sort`. |
| POST | `/contacts` | Create a contact. |
| GET | `/contacts/{id}` | One contact. |
| PATCH | `/contacts/{id}` | Edit the contact; requires `version`. |
| POST | `/contacts/{id}/archive` | Archive the contact. |
| GET | `/contacts/{id}/history` | Contact history from the audit log. |
| GET | `/opportunities` | Read-only. Filters: `account_id`, `stage`, `owner_id`. |
| GET | `/opportunities/{id}` | Read-only. |

**Database:** migration `0010` adds:
- `accounts`: `segment` and `preferred_channel`;
- `contacts`: `mobile`, `department`, `is_primary` (with a partial unique index), `preferred_channel`, `email_consent` + `email_consent_at`, and `do_not_call`.

Only new columns are added, so existing rows stay valid.

## Tests
- **Backend:** `tests/db/test_customer_data_api.py` has 54 tests on real PostgreSQL. They cover:
  - the happy paths and validation (including `javascript:` website links);
  - tenant isolation, role denial and record-level denial;
  - ID tampering: hidden or foreign accounts, parents and owners;
  - optimistic locking, the hierarchy rules, archive and restore;
  - the primary-contact switch and consent dating.

  11 deliberate bugs (mutation checks) were each caught by a failing test.
- **Unit:** `frontend/src/lib/customer-data.test.ts` covers the form rules, history lines, the relationship timeline and the list parameters.
- **E2E:** `frontend/e2e/customer-data.spec.ts` runs four journeys against the real stack:
  - a rep builds a customer 360;
  - deactivate, archive and restore;
  - others are blocked from someone's contact;
  - logging a call on a lead.
