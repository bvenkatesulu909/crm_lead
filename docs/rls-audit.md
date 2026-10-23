# RLS audit — 2026-10-23

## Enforced today

Six tables have ENABLE + FORCE row-level security and one policy each:

- `kb_documents`, `kb_chunks` (migration 0022): `tenant_id = crm_current_tenant()`.
- `leads` (migration 0029):
  `tenant_id = crm_current_tenant() AND (crm_lead_scope() = 'all' OR owner_id = crm_current_user())`.
- `users` (migration 0030): `tenant_id = crm_current_tenant()`. Login goes through the narrow
  `SECURITY DEFINER` function `identity_lookup_user(issuer, subject)` (owner `crm_owner`, fixed
  `search_path`, EXECUTE only for `crm_app`), which returns only id, tenant_id and is_active.
  The full User row is loaded after `bind_tenant()`.
- `access_requests` (migration 0031): `tenant_id = crm_current_tenant()`. Signup uses the
  narrow `SECURITY DEFINER` functions `access_request_latest` (latest status/tenant only) and
  `access_request_submit` (insert-only, active signup code + length validation), owned by
  `crm_owner` with EXECUTE only for `crm_app`.
- `outbox_jobs` (migration 0032): `tenant_id = crm_current_tenant()`. The worker claims one job
  through `outbox_claim(now, stale_before)` (`FOR UPDATE SKIP LOCKED`, returns only that job),
  then binds `app.tenant_id = job.tenant_id`. Schedulers iterate active tenants and bind each.

`crm_current_tenant()`, `crm_current_user()` and `crm_lead_scope()` are fail-closed when their
setting is unset (NULL), so an unbound connection sees no rows and cannot insert them.

`crm_app` has no BYPASSRLS; `crm_owner` does (migrations and test setup only).

A sales agent (scope "own") sees only leads they own; sales managers and tenant admins
(scope "all") see every lead in their tenant. A missing setting shows nothing.

Tests:

- `backend/tests/db/test_rls_leads.py` — 2 passed: agent own vs manager all, and no settings
  returns zero rows.
- `backend/tests/db/test_rls_identity.py` — 3 passed: login lookup then normal load, tenant B
  cannot read tenant A's user, and the function is not executable by PUBLIC.
- `backend/tests/db/test_rls_access_requests.py` — 4 passed: signup without a tenant,
  anonymous read/insert denied, tenant isolation, functions not PUBLIC.
- `backend/tests/db/test_rls_outbox.py` — 2 passed: two tenants' jobs run with the right
  tenant setting; a handler cannot read the other tenant's user; claim not PUBLIC.
- `backend/tests/db/test_rls_knowledge_deep.py` — 7 passed: select/insert/update/delete
  isolation, missing-context fail-closed, cross-tenant chunk FK, transaction-local tenant
  setting, and the app role cannot disable row security.

## Test bootstrap (owner-based)

Setup writes that must be visible to the restricted app role are created as `crm_owner`
(BYPASSRLS) and committed, then truncated after the test (`tests/db/conftest.py`:
`committed_world`, `clean_committed_data`). API requests and RLS assertions keep using
`crm_app` (`db_connection`), so the policies are genuinely exercised.
`clean_committed_data` finishes the app connection's transaction before TRUNCATE so API row
locks cannot block cleanup.

Rows created inside a test's rolled-back transaction (for example an extra lead used by a
report) cannot go through a second owner transaction: their tenant/user rows are uncommitted,
so the owner connection could not see those foreign keys. Those inserts call
`setup_lead_context()`, which applies the per-transaction settings a real request would set
(tenant + owner with scope "own", or scope "all" for an ownerless/manager row). It never
disables a policy or opens a fail-open path.

## Gap inventory

Run: `cd backend && .venv\Scripts\python -m scripts.rls_audit`

Current result (dev database, migration 0032):

- tenant tables: 47
- protected: 6 (kb_documents, kb_chunks, leads, users, access_requests, outbox_jobs)
- unprotected: 41, including accounts, contacts, opportunities,
  activities, quotes, orders, invoices, tickets, documents, products, notifications, audit_log,
  outbox_jobs, rag_queries, rag_feedback, assistant conversations/messages/tool_calls,
  portal_access_grants, lead_activities, lead_assignments.

Cross-tenant probe as `crm_app` with no tenant context:

| Table | Rows visible | Distinct tenants visible |
|---|---:|---:|
| users | 0 | 0 |
| access_requests | 0 | 0 |
| accounts | 187 | 2 |
| outbox_jobs | 0 | 0 |
| tickets | 60 | 1 in this dataset |
| leads | 0 | 0 |

Knowledge rows with no tenant context: 0. Lead rows with no tenant context: 0. User rows with
no tenant context: 0 (RLS working).

## Confirmed design blockers

1. Test/seed bootstrap — fixture and seed setup still writes through `crm_app` for many
   domains; Step 4 moves setup to the owner connection.
2. Remaining tenant tables (41) — each domain needs its own policy and tests (see above).

## Next

Step 4 owner-based test/seed bootstrap -> remaining domains (accounts/contacts,
sales/quotes/orders, support, documents, notifications/workflows/assistant).