# Handoff - crm-lead RLS

Worktree: E:\crm-lead-rls
Branch: rls-leads-policy
PR: https://github.com/bvenkatesulu909/crm_lead/pull/1 (do not merge without owner approval)

Read first: CLAUDE.md, docs/adr/0009-row-level-security.md, docs/rls-audit.md,
backend/tests/db/conftest.py.

## Done (2026-10-23)
- Step 4 (commit 9179646): test worlds built as crm_owner via committed_world; assertions on
  crm_app. seed_dev_data uses the owner URL. Fixed POST /platform/tenants 500 under users RLS.
  Full backend suite: 1143 passed, 4 skipped.
- Step 5 (commit 0c50bf8): migrations 0033-0035 put ENABLE + FORCE RLS + tenant policy on the
  remaining 41 tenant tables (47/47 now). 0036 ops_queue_counts() for /metrics (gauges were 0
  under RLS). Guard test tests/db/test_rls_tenant_tables.py. Full backend suite: 1150 passed,
  4 skipped; ruff, mypy, lint-imports clean.
- Step 6: docs (ADR 0009, rls-audit, auth, architecture, gap-analysis, deployment, plan,
  CLAUDE.md).

## Not done
- Development database (crm) is still at 0032: run `alembic upgrade head` (owner's call).
- Playwright has NOT been run against this branch. The servers on :8000/:3000 were running from
  the main checkout E:\crm-lead (older commit), so E2E there would not test this branch.

## Test-writing rules learned here
- Setup rows that the API must see: committed_world (owner) + commit; truncated afterwards.
- Setup inside the rolled-back transaction: bind the row's own tenant (bind_tenant),
  setup_lead_context for leads, bind_principal for direct service calls.
- Reads in tests bind their tenant explicitly: the worker binds every tenant in turn, so the
  setting left on the shared connection is often another tenant's.
- Never weaken a policy; never edit applied migrations.
