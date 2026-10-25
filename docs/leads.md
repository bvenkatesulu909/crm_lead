# Lead Management module

A **lead** is a possible customer who isn't yet qualified. This module captures leads, lets
sales staff work them through a fixed status flow, and converts qualified leads into an
account, a contact and (optionally) an opportunity.

Full machine-readable contract: [docs/api/openapi.json](api/openapi.json) (also browsable at
`http://127.0.0.1:8000/docs` while the API runs). Authentication and roles: [docs/auth.md](auth.md).

## Endpoints (`/api/v1/leads`)

| Method & path | What it does | Permission | Success |
|---|---|---|---|
| `POST /leads` | Create a lead | `lead:write:*` (+ `lead:assign` to set another owner) | 201 + `Location` |
| `GET /leads` | List, search, filter, sort, paginate | `lead:read:*` | 200 `LeadPage` |
| `GET /leads/{id}` | One lead | `lead:read:*` | 200 |
| `PATCH /leads/{id}` | Change details (needs `version`) | `lead:write:*` | 200 |
| `POST /leads/{id}/assign` | Give the lead to a sales employee | `lead:assign` | 200 |
| `POST /leads/{id}/status` | Change status (contacted / qualified / unqualified) | `lead:write:*` | 200 |
| `POST /leads/{id}/qualify` | Shortcut: → qualified | `lead:write:*` | 200 |
| `POST /leads/{id}/disqualify` | Shortcut: → unqualified (reason required) | `lead:write:*` | 200 |
| `POST /leads/{id}/convert` | Convert a qualified lead | `lead:convert` + write scope | 201, or 200 if already converted |
| `GET /leads/{id}/activities` | Timeline (calls, notes, automatic events) | `lead:read:*` | 200 |
| `POST /leads/{id}/activities` | Record call / e-mail / meeting / note | `lead:write:*` | 201 |
| `GET /leads/{id}/assignments` | Ownership history | `lead:read:*` | 200 |

**List parameters:** `q` (searches first/last name, company, e-mail; case-insensitive; `%` and
`_` are matched literally), `status` (repeatable), `owner_id`, `source`, `created_from`
(inclusive), `created_to` (exclusive), `account_id` (leads converted into that account), `sort` (`-created_at` default, `created_at`, `±updated_at`,
`±last_name`, `±company_name`), `limit` (1–200, default 50), `offset`. `total` counts only leads
you may see.

## Who can do what

| Role | Sees | Changes | Assigns | Converts |
|---|---|---|---|---|
| Tenant Admin | all leads of the tenant | all | ✔ | ✔ |
| Sales Manager | all leads of the tenant* | all | ✔ | ✔ |
| Sales Agent | **own** leads only | own | ✘ | own |
| Support Agent | nothing | – | – | – |
| Customer | nothing (no lead endpoints in the portal) | – | – | – |
| Super Admin | nothing (no tenant data) | – | – | – |

\* Sales teams don't exist yet, so a manager's "permitted scope" is the whole tenant. When
teams are added, only `policies.py` changes.

- A lead you may not see returns **404**, whether it belongs to a colleague or another tenant,
  or doesn't exist.
- Agents become the owner of leads they create. A tenant admin's new lead stays unassigned
  until someone assigns it.
- **Assignees** must be active staff of the same tenant with the `sales_agent` or
  `sales_manager` role (422 `invalid_assignee` otherwise). Roles are read from the CRM's role
  snapshot, which is refreshed at every sign-in; access itself is always checked on the live token.

## Status flow

```
new ──► contacted ──► qualified ──► converted   (only through /convert; final)
 │          │  ▲          │
 │          ▼  │          ▼
 └──────► unqualified ◄───┘   (unqualified → contacted re-opens a lead)
```

Any other change returns **409** `invalid_status_transition`. A converted lead is read-only:
updates, status changes and assignment return **409** `lead_converted`.

## Conversion

`POST /leads/{id}/convert`

```json
{
  "account": {"existing_account_id": null, "name": null},
  "opportunity": {"name": null, "amount": "25000.00", "currency": "EUR", "expected_close_date": null}
}
```

- **Account:** link an existing account you can see (`existing_account_id`), or create one
  (default name: the lead's company, else the person's name). An account you can't see → 404.
- **Contact:** always created from the lead's person data, linked to the account.
- **Opportunity:** created only if `opportunity` is sent. Amount is an exact decimal.
- New records are owned by the lead's owner and belong to the lead's tenant. The database's
  composite foreign keys make cross-tenant links impossible.
- **Atomic:** everything happens in one database transaction. If any step fails, nothing is
  saved (tested by forcing the opportunity step to fail).
- **Idempotent, no duplicates:** the lead row is locked (`SELECT … FOR UPDATE`) during
  conversion. A second request, even an exactly simultaneous one, waits and then gets the
  original result with `already_converted: true` and status 200; nothing new is created
  (tested with two parallel database connections).

## History and audit

| What | Where | Notes |
|---|---|---|
| Timeline | `lead_activities` | user entries (`note`, `call`, `email`, `meeting`) plus automatic `created`, `assigned`, `status_changed`, `converted` |
| Ownership history | `lead_assignments` | from → to, who assigned, reason. **Append-only** for the API |
| Audit trail | `audit_log` | `lead.created`, `lead.updated` (field-level old → new), `lead.assigned`, `lead.status_changed`, `lead.converted`; actor, request ID, time. **Append-only** for the API |

The API's database user has only `INSERT, SELECT` on `audit_log` and `lead_assignments`, so
even a bug in the application can't rewrite history. Event times use the real insert time
(`clock_timestamp()`), plus an ever-increasing `seq` number as a tie-breaker, so the order is
always exact.

## Errors

Every error is `application/problem+json`:

```json
{"type": "about:blank", "title": "Conflict", "status": 409,
 "detail": "A lead cannot go from 'unqualified' to 'qualified'.",
 "code": "invalid_status_transition", "request_id": "…"}
```

| Status | `code` | When |
|---|---|---|
| 401 | – | missing / invalid token |
| 403 | `forbidden` / – | role lacks the permission (e.g. agent assigning) |
| 404 | `lead_not_found`, `not_found` | lead or linked account not visible to you |
| 409 | `invalid_status_transition`, `lead_converted`, `version_conflict`, `conflict` | state conflicts |
| 422 | `invalid_assignee` / field `errors` | bad input; unknown fields (e.g. `tenant_id`, `status` on PATCH) are rejected |

## Database changes (migration `0003`)

| Table / column | Purpose |
|---|---|
| `users.roles` | last-known CRM roles (for assignment checks) |
| `opportunities` | minimal opportunity table (stage, NUMERIC amount, ISO currency) used by conversion |
| `leads.converted_opportunity_id` + `ck_leads_converted_has_records` | a converted lead always points at its account and contact |
| `lead_activities`, `lead_assignments`, `audit_log` | timeline, ownership history, audit trail |

## Files

| File | Role |
|---|---|
| `backend/app/modules/leads/models.py` | tables and database constraints |
| `backend/app/modules/leads/transitions.py` | the status flow (pure, unit-tested) |
| `backend/app/modules/leads/schemas.py` | request/response contracts and input validation |
| `backend/app/modules/leads/policies.py` | which leads a user may see / change |
| `backend/app/modules/leads/repository.py` | queries: search, filter, sort, paginate, row locks |
| `backend/app/modules/leads/service.py` | business rules, conversion, history, audit |
| `backend/app/modules/leads/router.py` | HTTP endpoints + OpenAPI documentation |
| `backend/app/core/audit.py` | `audit_log` table and `record_audit()` |
| `backend/app/core/errors.py` | `DomainError` family → Problem Details with `code` |
| `backend/app/modules/sales/` | `Opportunity` model + `create_opportunity()` |
| `backend/app/modules/{accounts,contacts}/api.py` | creation helpers used by conversion |
| `backend/scripts/export_openapi.py` | writes `docs/api/openapi.json` |

## Not done yet

- Duplicate-lead detection (same e-mail): planned with lead capture forms.
- Lead deletion / archiving (soft delete exists in the table, no endpoint yet).
- Sales teams to narrow a manager's scope; a generic activities module (Phase 9) may absorb
  `lead_activities`.
- Search uses `ILIKE`; for large data volumes add a `pg_trgm` index or full-text search.

## Real-estate wishes (ADR 0013, step PC2, 2026-10-25)

Four optional fields on every lead, for home buyers (migration 0040):

| Field | Meaning | Rules (API and database) |
|---|---|---|
| `property_type` | `apartment`, `villa`, `plot` or `commercial` | other values refused |
| `budget_min_inr`, `budget_max_inr` | budget in **whole rupees** (`BIGINT`, never a float) | ≥ 0, at most 1 lakh crore (typo guard), minimum ≤ maximum |
| `location` | area or city they want, e.g. "Kokapet, Hyderabad" | ≤ 160 characters |

- A change may send one side of the budget only; it is compared with the saved other side and
  refused with `422 budget_out_of_order` if they'd be out of order. The database checks the same
  rules (`ck_leads_property_type_allowed`, `ck_leads_budget_not_negative`,
  `ck_leads_budget_in_order`).
- The lead form has a "Property wishes" group. Budgets can be typed as `12000000`,
  `1,20,00,000`, `1.2 Cr` or `80 L`; the web app turns them into whole rupees with digit
  arithmetic (no rounding). The lead page shows them as "₹1.2 Cr – ₹1.5 Cr".
- Changes are in the audit trail like every other lead field.
- Tests: `backend/tests/db/test_lead_real_estate.py`, `frontend/src/lib/lead-real-estate.test.tsx`,
  `frontend/e2e/lead-property.spec.ts`.
