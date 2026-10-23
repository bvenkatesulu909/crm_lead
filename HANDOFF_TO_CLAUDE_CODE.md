# Handoff to Claude Code - crm-lead RLS

Worktree: E:\crm-lead-rls
Branch: rls-leads-policy
PR: https://github.com/bvenkatesulu909/crm_lead/pull/1
Base: main ec41dbc (do not merge without owner approval)

Read first: CLAUDE.md, architecture.md, docs/adr/0009-row-level-security.md,
docs/rls-audit.md, backend/app/core/db.py, backend/app/modules/identity/, backend/tests/db/.

## Completed
- Leads RLS 0029 (commit dd7b486).
- CRM-101 support boundary tests (commit 97f4a13).
- Users RLS 0030 + identity_lookup_user SECURITY DEFINER.
- access_requests RLS 0031 + access_request_latest / insert-only access_request_submit.
- outbox_jobs RLS 0032 + outbox_claim (FOR UPDATE SKIP LOCKED); worker binds job.tenant_id;
  schedulers iterate active tenants.
- Migrations 0030-0032 applied to dev DB.

Focused tests (all pass):
  cd E:\crm-lead-rls\backend
  E:\crm-lead\backend\.venv\Scripts\python -m pytest tests\db\test_rls_outbox.py tests\db\test_rls_access_requests.py tests\db\test_rls_identity.py tests\db\test_rls_leads.py -q
  => 11 passed

## Current blocker: Step 4
Full suite is RED in fixtures with:
  new row violates row-level security policy for table "users"
because world fixtures use db_session (crm_app) to create users/access_requests/outbox jobs.

A central owner db_session + commit-on-flush + autouse truncate was attempted and REVERTED:
it made assistant tool-call records disappear. Do not repeat that shortcut.

Proper approach: migrate shared world fixtures to committed_owner_data (owner), commit before
API calls, clean up; keep API/RLS assertions on crm_app. Start with test_authorization.py and
test_assistant_api.py, then invoices/orders, knowledge/outbox, then all tests/db. Update
scripts/seed_dev_data.py to use the owner/migration URL. Then run the FULL suite and show output.

## After Step 4
Step 5: FORCE RLS + tenant policy on remaining 41 tenant tables, guard tests, full pytest,
ruff, mypy, lint-imports, Playwright.
Step 6: docs.

## Guardrails
- Never edit migration 0022 or applied migrations; add new ones with downgrade.
- No raw string-built SQL; bound params only.
- SECURITY DEFINER: fixed search_path, minimal columns, EXECUTE only crm_app.
- No secrets committed. Ask before destructive DB/volume commands. Do not merge PR.
