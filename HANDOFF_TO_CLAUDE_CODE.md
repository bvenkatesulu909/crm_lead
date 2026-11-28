# Handoff - where to start

This file used to hold the handoff notes for the Row-Level Security work (PR #1, branch
`rls-leads-policy`). That work is finished and merged into `main` (see `docs/rls-audit.md` and
ADR 0009), so those notes are out of date and have been removed.

For the current state of the project, read:

- `CLAUDE.md` - working rules, commands and the "Current status" section (kept up to date).
- `implementation-plan.md` - the phases and what is next.
- `docs/gap-analysis.md` - the full inventory and the remaining work.

## Test-writing rules learned during the RLS work (still valid)

- Setup rows that the API must see: `committed_world` (owner) + commit; truncated afterwards.
- Setup inside the rolled-back transaction: bind the row's own tenant (`bind_tenant`),
  `setup_lead_context` for leads, `bind_principal` for direct service calls.
- Reads in tests bind their tenant explicitly: the worker binds every tenant in turn, so the
  setting left on the shared connection is often another tenant's.
- Never weaken a policy; never edit applied migrations.
