# RLS audit — 2026-10-22

## Enforced today

Three tables have ENABLE + FORCE row-level security and one policy each:

- `kb_documents`, `kb_chunks` (migration 0022): `tenant_id = crm_current_tenant()`.
- `leads` (migration 0029):
  `tenant_id = crm_current_tenant() AND (crm_lead_scope() = 'all' OR owner_id = crm_current_user())`.

`crm_current_tenant()`, `crm_current_user()` and `crm_lead_scope()` are fail-closed when their
setting is unset (NULL), so an unbound connection sees no rows and cannot insert them.

`crm_app` has no BYPASSRLS; `crm_owner` does (migrations and test setup only).

A sales agent (scope "own") sees only leads they own; sales managers and tenant admins
(scope "all") see every lead in their tenant. A missing setting shows nothing.

Tests:

- `backend/tests/db/test_rls_leads.py` — 2 passed: agent own vs manager all, and no settings
  returns zero rows.
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

Current result (dev database, migration 0029):

- tenant tables: 47
- protected: 3 (kb_documents, kb_chunks, leads)
- unprotected: 44, including users, access_requests, accounts, contacts, opportunities,
  activities, quotes, orders, invoices, tickets, documents, products, notifications, audit_log,
  outbox_jobs, rag_queries, rag_feedback, assistant conversations/messages/tool_calls,
  portal_access_grants, lead_activities, lead_assignments.

Cross-tenant probe as `crm_app` with no tenant context:

| Table | Rows visible | Distinct tenants visible |
|---|---:|---:|
| users | 71 | 2 |
| access_requests | 22 | 2 |
| accounts | 187 | 2 |
| outbox_jobs | 143 | 1 in this dataset |
| tickets | 60 | 1 in this dataset |
| leads | 0 | 0 |

Knowledge rows with no tenant context: 0. Lead rows with no tenant context: 0 (RLS working).

## Confirmed design blockers

1. Identity — `users` / `access_requests` have no policies and no pre-tenant lookup function;
   login/signup would break if RLS were enabled without a SECURITY DEFINER exception.
2. Worker — `outbox_jobs` has no RLS and no claim function; the worker uses the app role.
3. Remaining tenant tables — each domain needs its own policy and tests (see the list above).

## Next

0030 worker claim + dedicated BYPASSRLS worker role -> 0031 identity bootstrap exceptions ->
0032+ remaining domains (accounts/contacts, sales/quotes/orders, support, documents,
notifications/workflows/assistant).
