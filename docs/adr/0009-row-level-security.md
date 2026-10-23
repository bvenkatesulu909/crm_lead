# ADR 0009 — PostgreSQL Row-Level Security as defence in depth

- **Status:** Accepted (2026-10-21, staged rollout). **Implemented 2026-10-23:** all 47 tables
  with `tenant_id` have ENABLE + FORCE RLS and a tenant policy (0022, 0029-0035), with narrow
  SECURITY DEFINER exceptions for login, sign-up, the worker claim and the metrics counts. The
  worker runs as `crm_app` (no separate BYPASSRLS role was needed). See "Implementation status".
- **Date:** 2026-10-20
- **Deciders:** Project owner
- **Depends on:** ADR 0002 (tenant from the verified identity); independent of ADR 0008

## Context

Tenant isolation is enforced today by application policies (SQL filters built in each module's
`policies.py`), composite same-tenant foreign keys and tests. `architecture.md` §5 plans a
second layer: PostgreSQL **Row-Level Security (RLS)** on every tenant table, with
`app.tenant_id` set per transaction - defence in depth, so a forgotten filter cannot leak rows.

Findings from the code audit (all verified against the tree at migration 0019):

- **Roles are already right.** The API connects as a non-owner `app` role with only
  SELECT/INSERT/UPDATE/DELETE on tables; Alembic uses a separate `owner` role. The app role has no
  BYPASSRLS and is not the table owner, so RLS will apply to it.
- **Transaction lifecycle is the hard part.** One synchronous Session per request, sqlalchemy
  autobegin, commits in routers - but also **mid-request commits** inside
  `identity.service.get_principal()`, quotes and reports. A one-shot `SET LOCAL` would be
  discarded at the first such commit. A session event listener must re-issue the tenant setting
  at the start of **every** transaction.
- **Coverage.** 43 of 45 tables carry `tenant_id`. The exceptions are `tenants` (root, tenant is
  its own id) and `signup_code_attempts` (identity-scoped). No tenant-owned table lacks the column.
- **The worker crosses tenants.** It claims outbox jobs across all tenants (outbox claim,
  activity reminders, workflow schedules) using the same app-role engine. Under RLS it would fail
  closed and silently stop.
- **Tests would break.** About 20 database-test fixtures insert tenants/users/accounts directly
  through the app role with no tenant setting; all would fail `WITH CHECK` policies. Some tests
  also delete from `tenants` directly.
- **Bootstrap lookups** (`users` by issuer+subject before the tenant is known, sign-up code
  lookup) cannot run under a tenant policy.

## Decisions (proposed)

1. **Enforcement.** On every table with `tenant_id`: `ENABLE` + `FORCE ROW LEVEL SECURITY`
   and one policy with both `USING` and `WITH CHECK`:
   `tenant_id = crm_current_tenant()`, where `crm_current_tenant()` reads
   `NULLIF(current_setting('app.tenant_id', true), '')::uuid`. Missing setting means **no rows**
   (fail closed), and inserts/updates cannot create rows for another tenant.

2. **Tenant setting per transaction.** Store the tenant on the Session (`session.info`), not in a
   ContextVar (FastAPI dependencies can run in a threadpool). A SQLAlchemy event listener
   re-issues `select set_config('app.tenant_id', :tenant, true)` at the start of every
   transaction. The dependency that sets it runs **after** the principal is resolved. Plain
   `SET` is never used - it would leak to the next request through the pool.

3. **Bootstrap exceptions, narrow and documented.**
   - `tenants` and `signup_code_attempts` are outside RLS (no tenant column / identity-scoped).
   - The `(issuer, subject) -> user` lookup and the sign-up-code flow go through
     `SECURITY DEFINER` functions owned by the owner role, granted only to the app role, returning
     the minimum fields. `users` itself is RLS-protected for all normal queries.

4. **A separate worker role.** A dedicated `crm_worker` role with `BYPASSRLS` and only the grants
   the worker needs, used by `python -m app.worker`. The API never uses it. (Alternative: run the
   worker as the owner role - simpler, but broader than necessary.)

5. **Staged migrations by domain**, each additive and reversible:
   0020 core (`audit_log`, `outbox_jobs`, identity tables), 0021 customers, 0022
   sales/quotes/orders, 0023 documents/notifications/workflows/assistant. A failure in one domain
   stays local; rollback is `DISABLE ROW LEVEL SECURITY` for that group.

6. **Test strategy.** Fixture setup uses a bootstrap connection that bypasses RLS (owner role
   with `BYPASSRLS` or the dedicated worker/setup role); API requests and assertions still use the
   app role, so RLS is genuinely exercised. New tests: raw `SELECT` with no setting -> 0 rows;
   tenant A setting -> only A; wrong tenant -> 0; cross-tenant INSERT rejected; a catalog test
   asserting every table with a `tenant_id` column has RLS + FORCE + a policy (protects future
   migrations); the worker can claim jobs across tenants; an API request really sets the setting.

7. **Kill switch is operational, not a feature flag.** Recovery is an owner-run SQL statement or a
   migration (`ALTER TABLE ... DISABLE ROW LEVEL SECURITY`), never an app setting - a flag the app
   role can change would remove the defence itself.

## Consequences

- A missing tenant context becomes an empty result instead of a leak: fail-closed. That will
  surface bugs (worker, scripts, seeding) loudly and is the point; step order must keep the app
  green at every commit.
- `FORCE` also applies to the owner connection, so migration guards that read data
  (`SELECT ... FROM users`) need either a BYPASSRLS owner role or rewriting; the owner already
  has full DDL rights, so granting it `BYPASSRLS` is acceptable and must be documented.
- Dev scripts (`seed_dev_data`) and any direct SQL tooling must set the tenant or use the
  bootstrap role.
- Performance cost is one indexed UUID comparison per row; acceptable at this scale.
- RLS does **not** defend against a compromised app process (it could set the GUC): it defends
  against missing filters and coding mistakes, which is exactly the failure mode this project has
  had none of so far but cannot rule out.

## Implementation status (2026-10-23, staged)

- **Owner bootstrap (2026-10-21):** `crm_owner` has `BYPASSRLS` **for migrations/test setup only**
  (`infrastructure/postgres/init/04-owner-bypassrls.sh`); `crm_app` remains non-superuser and
  non-BYPASSRLS. Test fixtures must create data with an owner session while API/RLS tests use
  `crm_app`; that fixture split is the remaining prerequisite before 0029.
- **Leads + test bootstrap (2026-10-22):** `bind_user()` stores `app.user_id` and
  `app.lead_scope`; the `after_begin` listener re-applies tenant, user and scope after every
  commit/rollback. `identity.service.resolve_principal()` binds scope `all` for
  `sales_manager` and `tenant_admin`, `own` otherwise. Migration **0029** adds
  `crm_current_user()` and `crm_lead_scope()` and enables FORCE RLS on `leads` with a policy
  checking the tenant and (`scope = 'all'` OR `owner_id = current user`) for both USING and
  WITH CHECK. World/setup fixtures now build data through `crm_owner` and commit it
  (`committed_world`); `clean_committed_data` truncates afterwards and finishes the app
  transaction first. Setup rows that must stay in a test's rolled-back transaction use an
  explicit tenant/owner context (`setup_lead_context`). API and RLS assertions still run as
  `crm_app`; no policy was weakened. Verified: full backend suite 1123 passed, 4 skipped;
  `test_rls_leads.py` 2 passed; `rls_audit` shows `leads` protected and 0 lead rows without
  tenant context.
- **Identity lookup + users RLS (2026-10-23):** Migration **0030** adds the narrow
  `identity_lookup_user(issuer, subject)` `SECURITY DEFINER` function owned by `crm_owner`
  (fixed `search_path`, returns only id/tenant_id/is_active, EXECUTE only for `crm_app`), and
  FORCE RLS on `users` with a tenant-isolation policy. `resolve_principal()` calls the
  function, checks active status, binds the tenant and only then loads the full User row.
  Verified: `test_rls_identity.py` 3 passed; dev RLS/force flags true, policy
  `users_tenant_isolation`, app EXECUTE true, PUBLIC EXECUTE false.
- **Worker claim + schedulers (2026-10-23):** Migration **0032** adds
  `outbox_claim(now, stale_before)` (SECURITY DEFINER, `FOR UPDATE SKIP LOCKED`, returns only
  the claimed job) and FORCE RLS on `outbox_jobs`. The worker binds `job.tenant_id` before the
  handler. Reminder/workflow schedulers iterate active tenants and bind each tenant before
  running. Verified: `test_rls_outbox.py` 2 passed.
- **Done:** `crm_current_tenant()` (fail-closed when unset); `bind_tenant`
  (`app/core/db.py`) sets `app.tenant_id` from the verified Principal and an `after_begin`
  listener re-applies it after every commit/rollback; identity resolution binds it; the worker
  binds each job's tenant; migration **0022** enables **FORCE** RLS + a tenant-isolation policy on
  `kb_documents` and `kb_chunks`.
- **Verified:** raw app-role queries return 0 rows without the setting, only the bound tenant's
  rows with it, and 0 for another tenant; policy/force flags checked by a test; demo seeding and
  the knowledge tests work under RLS.
- **Test/seed bootstrap (step 4, 2026-10-23):** shared test worlds are built through
  `committed_world` (crm_owner) and committed; API calls and assertions stay on `crm_app`.
  Rolled-back setup binds the row's own tenant like a request; tests that call services directly
  use `bind_principal()`. `seed_dev_data` connects with the owner (migration) URL. Found and
  fixed on the way: `POST /platform/tenants` returned 500 under users RLS - the new tenant's
  server-generated id is now bound before its first admin is inserted. Verified: full backend
  suite 1143 passed, 4 skipped.
- **Remaining domains (step 5, 2026-10-23):** migrations **0033** (customers, activities,
  audit), **0034** (sales, quotes, orders, billing) and **0035** (support, documents,
  notifications, workflows, assistant, RAG logs) enable FORCE RLS with
  `<table>_tenant_isolation` (`tenant_id = crm_current_tenant()` for USING and WITH CHECK) on
  the remaining 41 tables; each has a downgrade. **0036** adds `ops_queue_counts()` because the
  `/metrics` queue gauges had silently become 0 under RLS (aggregates per status only, EXECUTE
  only for `crm_app`). Guard test `test_rls_tenant_tables.py` fails any future table with a
  `tenant_id` column but no FORCE RLS + tenant policy. Verified: full backend suite 1150
  passed, 4 skipped; ruff, mypy, lint-imports clean; `rls_audit` 47/47 protected. Playwright not
  yet run against this branch.
- **Decision 4 in practice:** no `crm_worker` BYPASSRLS role. The worker claims through
  `outbox_claim()` and then binds each job's tenant, so it is as restricted as the API.
- **Next:** apply 0033-0036 to the development database and run the Playwright suite against
  this branch; then Teams (record-level, not RLS).

## Open questions for the owner

1. **Worker credentials:** resolved 2026-10-23 - neither: the worker stays on `crm_app`, claims
   through `outbox_claim()` and binds each job's tenant.
2. **Owner `BYPASSRLS`:** confirm the migration role may bypass RLS for bootstrap and tests
   (recommended, documented), or keep `FORCE` strict and rewrite the few guards?
3. **Test setup:** resolved 2026-10-22 — owner-connection fixtures for committed data, plus an
   explicit tenant/owner context for rows that stay in a test's rolled-back transaction.
4. **Exceptions:** accept `tenants`, `signup_code_attempts` and the SECURITY DEFINER identity
   lookups (recommended, documented in `docs/auth.md`)?
5. **Rollout:** enable per domain (recommended) or all tables in one migration?
6. **Timing:** is RLS required before real data goes online, or may the deployment stay limited to
   one organisation until it lands (the deployment checklist allows either)?