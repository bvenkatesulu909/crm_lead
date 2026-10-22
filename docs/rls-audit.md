# RLS audit — 2026-10-21

## Enforced today

Only two tables have RLS (migration 0022), both ENABLE + FORCE with one policy
(tenant_id = crm_current_tenant()):

- kb_documents
- kb_chunks

crm_current_tenant() is fail-closed when app.tenant_id is unset.
crm_app has no BYPASSRLS; crm_owner does (migrations/test setup only).

Deep tests: backend/tests/db/test_rls_knowledge_deep.py — 7 passed:
select/insert/update/delete isolation, missing-context fail-closed, cross-tenant chunk FK,
transaction-local tenant setting, and app role cannot disable row security.

## Gap inventory

Run: cd backend && .venv\Scripts\python -m scripts.rls_audit

Current result:

- tenant tables: 47
- protected: 2 (kb_documents, kb_chunks)
- unprotected: 45, including users, access_requests, accounts, contacts, leads, opportunities,
  activities, quotes, orders, invoices, tickets, documents, products, notifications, audit_log,
  outbox_jobs, rag_queries, rag_feedback, assistant conversations/messages/tool_calls,
  portal_access_grants.

Cross-tenant probe as crm_app with no tenant context:

| Table | Rows visible | Distinct tenants visible |
|---|---:|---:|
| users | 71 | 2 |
| access_requests | 22 | 2 |
| accounts | 187 | 2 |
| outbox_jobs | 142 | 1 in this dataset |
| tickets | 59 | 1 in this dataset |

Knowledge rows with no tenant context: 0 (RLS working).

## Confirmed design blockers

1. Identity — users / access_requests have no policies and no pre-tenant lookup function;
   login/signup would break if RLS were enabled without 0029.
2. Worker — outbox_jobs has no RLS and no claim function; worker uses the same app role.
3. Test bootstrap — owner setup fixtures exist (owner_engine, committed_owner_data,
   clean_committed_data), but world/setup fixtures still create through crm_app; 0029
   would still break them.

## Next

0029 identity exceptions -> test-fixture migration -> 0030 remaining tables -> 0031 worker claim.
