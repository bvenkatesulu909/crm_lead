# RLS audit — 2026-10-23

## Enforced today

**All 47 tables with a `tenant_id` column** have ENABLE + FORCE row-level security and a
tenant policy. Tables without `tenant_id` are the documented exceptions: `tenants` (the root),
`signup_code_attempts` (identity-scoped) and `service_heartbeats` (worker liveness, no tenant
data).

| Migration | Tables | Policy |
|---|---|---|
| 0022 | `kb_documents`, `kb_chunks` | `tenant_id = crm_current_tenant()` |
| 0029 | `leads` | tenant **and** (`crm_lead_scope() = 'all'` OR `owner_id = crm_current_user()`) |
| 0030 | `users` | `tenant_id = crm_current_tenant()` |
| 0031 | `access_requests` | `tenant_id = crm_current_tenant()` |
| 0032 | `outbox_jobs` | `tenant_id = crm_current_tenant()` |
| 0033 | `accounts`, `contacts`, `portal_access_grants`, `lead_activities`, `lead_assignments`, `activities`, `audit_log` | `tenant_id = crm_current_tenant()` |
| 0034 | `opportunities`, `opportunity_stage_changes`, `products`, `price_books`, `price_book_entries`, `quotes`, `quote_lines`, `quote_events`, `quote_number_counters`, `quote_settings`, `orders`, `order_lines`, `order_status_events`, `order_number_counters`, `invoices`, `invoice_lines`, `credit_notes`, `credit_note_lines`, `payments`, `billing_number_counters` | `tenant_id = crm_current_tenant()` |
| 0035 | `tickets`, `ticket_comments`, `ticket_number_counters`, `documents`, `notifications`, `notification_preferences`, `workflow_rules`, `workflow_runs`, `assistant_conversations`, `assistant_messages`, `assistant_pending_actions`, `assistant_tool_calls`, `rag_queries`, `rag_feedback` | `tenant_id = crm_current_tenant()` |

Every policy uses the same expression for USING and WITH CHECK, so rows can neither be read
nor written for another tenant. `crm_current_tenant()`, `crm_current_user()` and
`crm_lead_scope()` are fail-closed when their setting is unset (NULL): an unbound connection
sees no rows and cannot insert any.

RLS is the **second** layer. Record-level rules (owner, team, portal grants) stay in each
module's `policies.py`; RLS guarantees that a forgotten tenant filter cannot leak another
organisation's data.

`crm_app` has no BYPASSRLS; `crm_owner` does (migrations and test setup only).

## Narrow SECURITY DEFINER exceptions

Each is owned by `crm_owner`, has a fixed `search_path`, is executable only by `crm_app` (not
PUBLIC) and returns the minimum needed:

| Function | Why it cannot run under a tenant | Returns |
|---|---|---|
| `identity_lookup_user(issuer, subject)` (0030) | login: the tenant is not known yet | id, tenant_id, is_active |
| `access_request_latest(issuer, subject)` (0031) | sign-up status before membership | latest status + tenant |
| `access_request_submit(...)` (0031) | sign-up with an organisation code | insert only; request id + tenant |
| `outbox_claim(now, stale_before)` (0032) | the worker finds a due job before its tenant | the one claimed job |
| `ops_queue_counts()` (0036) | the `/metrics` scrape has no tenant | counts per status only - no ids |

## How the tenant is set

- API: `identity.service.resolve_principal()` looks up the user through
  `identity_lookup_user`, then `bind_tenant()` (+ `bind_user()` for the lead scope). An
  `after_begin` listener re-applies the settings after every commit/rollback.
- Platform "create organisation": binds the **new, server-generated** tenant id before inserting
  its first admin (fixed 2026-10-23; it returned 500 under users RLS).
- Worker: claims through `outbox_claim`, then binds `job.tenant_id`. Schedulers iterate active
  tenants and bind each one in its own transaction.
- Scripts: `seed_dev_data` connects as the owner (migration URL); the knowledge scripts bind each
  tenant.

## Tests

- `backend/tests/db/test_rls_tenant_tables.py` — the guard for future migrations: every table
  with `tenant_id` has ENABLE + FORCE and a policy whose USING and WITH CHECK both use
  `crm_current_tenant()`; no other table may appear without `tenant_id`; with real data in two
  tenants, no context shows 0 rows in every tenant table and each tenant sees only itself;
  cross-tenant INSERT and tenant-changing UPDATE are rejected; another tenant's rows cannot be
  updated or deleted; `crm_app` cannot disable RLS or set `row_security = off`.
- `test_rls_leads.py`, `test_rls_identity.py`, `test_rls_access_requests.py`,
  `test_rls_outbox.py`, `test_rls_knowledge*.py` — the per-domain behaviour above.
- `test_observability.py::test_queue_gauges_count_every_tenant_under_rls` — metrics count every
  tenant.
- Full backend suite (2026-10-23, crm_test at 0036): **1150 passed, 4 skipped** (opt-in live
  assistant). Playwright was **not** run for this change yet.

## Test bootstrap (owner-based)

Setup writes that must be visible to the restricted app role are created as `crm_owner`
(BYPASSRLS) and committed, then truncated after the test (`tests/db/conftest.py`:
`committed_world`, `clean_committed_data`). API requests and RLS assertions keep using
`crm_app` (`db_connection`), so the policies are genuinely exercised.

Rows created inside a test's rolled-back transaction cannot go through a second owner
transaction (their foreign keys may be uncommitted). Those helpers give the session exactly the
context a real request would have: `bind_tenant` for the row's own tenant, `setup_lead_context`
for leads, `bind_principal` for tests that call a service directly with a Principal. Reads in
tests bind the tenant they are about explicitly - the worker binds every tenant in turn, so the
setting left on the shared test connection is not necessarily the one a test means. Nothing
disables a policy or opens a fail-open path.

## Gap inventory

Run: `cd backend && .venv\Scripts\python -m scripts.rls_audit` (exit code 1 if any tenant table
is unprotected or shows rows without a tenant context).

Result against `crm_test` at migration 0036: tenant tables 47, protected 47, unprotected none,
47 policies, `crm_app` BYPASSRLS false, `crm_owner` BYPASSRLS true.

Result against the development database `crm` (upgraded to 0036 on 2026-10-23): tenant tables
47, protected 47, unprotected none; as `crm_app` with no tenant context **every** tenant table
shows 0 rows, while the owner role still sees the data (187 accounts, 60 tickets). Before step 5
the same probe showed 187 accounts from 2 tenants and 60 tickets.

## Next

- Run the Playwright suite against this branch's API and web app (the development database is
  already at 0036).
- Teams (manager hierarchies) - record-level, not RLS.
