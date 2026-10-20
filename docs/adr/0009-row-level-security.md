# ADR 0009 — PostgreSQL Row-Level Security as defence in depth

- **Status:** Proposed (2026-10-20; design audited against the code; waiting for the owner's
  decisions below; no code written yet)
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

## Open questions for the owner

1. **Worker credentials:** a dedicated `crm_worker` role with `BYPASSRLS` (recommended), or run the
   worker with the owner role?
2. **Owner `BYPASSRLS`:** confirm the migration role may bypass RLS for bootstrap and tests
   (recommended, documented), or keep `FORCE` strict and rewrite the few guards?
3. **Test setup:** owner-connection fixtures (recommended) or per-fixture tenant context?
4. **Exceptions:** accept `tenants`, `signup_code_attempts` and the SECURITY DEFINER identity
   lookups (recommended, documented in `docs/auth.md`)?
5. **Rollout:** enable per domain (recommended) or all tables in one migration?
6. **Timing:** is RLS required before real data goes online, or may the deployment stay limited to
   one organisation until it lands (the deployment checklist allows either)?
