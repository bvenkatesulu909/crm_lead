# ADR 0008 — Teams and team-scoped visibility

- **Status:** Proposed (2026-10-20; waiting for the owner's decisions below; no code written yet)
- **Date:** 2026-10-20
- **Deciders:** Project owner

## Context

Gap-analysis Phase C promised **teams**, so a sales manager can see their team's records instead
of the whole tenant. Today there is only a permission scope `:all` ("all records of my tenant")
and `:own`; the dashboard's per-rep table is presentation, not authorization.

Findings from the code audit:

- Nine owner-scoped modules build their visibility in `policies.py`: accounts, contacts, leads,
  opportunities, activities, tickets, orders, invoices, quotes (27 policy functions). Ownership is
  not uniform: tickets use assignee + account, orders and invoices derive from the account, quotes
  are owner-or-account, activities use assignee/creator plus the linked record.
- Modules may import only `app.core` and another module's `api.py`. `identity.api` already
  exposes `granted_account_ids()` to five policy files, so it is the natural place for the team
  roster.
- There are no teams tables; the migration head is 0019.

## Decisions (proposed)

1. **Data model.** Two tenant-owned tables:
   - `teams`: `id`, `tenant_id`, `name`, `manager_user_id`, timestamps; unique
     `(tenant_id, name)`, unique `(tenant_id, id)` as a composite-FK target, composite FK
     `(tenant_id, manager_user_id) -> users(tenant_id, id)`.
   - `team_members`: `id`, `tenant_id`, `team_id`, `user_id`, `created_at`; unique
     `(tenant_id, user_id)` (**one team per user** in v1), composite FKs, index
     `(tenant_id, team_id)`.
   The team lead is **data** (`teams.manager_user_id`), not a CRMM role: roles come only from
   Keycloak and the fixed RBAC table (ADR 0002 rules), and a "team_lead" role would mean a realm
   change and token mapping for a fact that lives in one table.

2. **A team permission scope.** Add `:team` to the read/write permissions of the nine modules
   (for example `account:read:team`) and grant it to `sales_manager`. `tenant_admin`,
   `support_agent` and the per-tenant Automation identity keep `:all`: support and automation
   must not go blind, and automation rules act across teams. Permissions remain the single source
   of truth in `backend/app/core/auth/rbac.py`.

3. **What "team" means.** A team scope sees rows whose responsible user belongs to the caller's
   team, **plus unowned rows** (the "No owner" queue shown on dashboards). Unowned rows are part
   of the assignment work, and hiding them would silently drop leads. Strict "team only" would
   need a claim-unassigned flow first and is not proposed.

4. **Roster on the Principal.** `resolve_principal()` loads the caller's team member IDs (one
   indexed query, cached per request) and `identity.api` exposes `team_member_ids(principal)`,
   mirroring `granted_account_ids()`. Policies use that set; write checks use it too (a boolean
   `can_write()` needs a set, not a subquery).

5. **Admin surface.** `/api/v1/tenant/teams` (list/create/update/delete) and
   `/tenant/teams/{id}/members`, permissions `tenant:team:read` / `tenant:team:manage`:
   tenant admins manage all teams; a sales manager may read the team they lead. `/me` gains the
   caller's team; the Users page gains a Team column and a Teams card.

6. **Rollout in five reviewable steps**, each shippable on its own:
   1. Migration **0020**: create both tables, constraints and indexes (pure DDL, no behaviour).
   2. Migration **0021**: idempotent backfill - one team per tenant, manager = an active
      `sales_manager`, members = active sales staff (`WHERE NOT EXISTS`).
   3. Code: `:team` permissions, roster, visibility helper and unit tests - while
      `sales_manager` still has `:all`, so **nothing changes for users yet**.
   4. Admin API + Users-page UI; admins curate real teams.
   5. Flip: `sales_manager` moves from `:all` to `:team` (read scopes first, then write),
      one dict edit that is trivially reversible; update the tests that assert managers see the
      whole tenant.

## Consequences

- Visible behaviour changes only at step 6.5, and only for `sales_manager`.
- About 10 policy files, 4 subquery helpers, 7 metrics modules and the dashboard/report team
  tables are touched; the main user-facing risk is a manager losing sight of records owned by
  people outside their team.
- New tests: team boundary (a record owned by another team is 404/absent), role denial, tenant
  isolation, schema constraints, migration roundtrip; `docs/api/openapi.json` is regenerated.
- Background paths that build a "staff principal" (notifications, approver fan-out) must load
  teams too, or notifications silently narrow.
- Teams stay **application-level**. PostgreSQL RLS (ADR 0009) only knows the tenant; team
  membership varies per request and would need a second GUC, which is the same trust level as
  the policy - so RLS is not the right layer for teams.

## Open questions for the owner

1. **Membership:** one team per user in v1 (recommended), or must someone belong to several?
2. **Manager visibility:** team + unowned rows (recommended), or strictly team only?
3. **Writes:** should `:team` also govern writes, or keep writes on `:all` for now? (recommended:
   yes, but flip reads first.)
4. **Approval rights:** may a team lead still approve quotes above the limit (a `:all`-style
   capability that is not about visibility)? (recommended: yes.)
5. **Backfill:** create one team per tenant with active sales staff now (recommended - keeps
   today's visibility until admins curate), or start empty?
