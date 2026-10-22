# Project inventory (generated)

*Generated on 2026-10-21 by `python -m scripts.report_inventory` (run in `backend/` with the venv active).*

This file records counts and routes, not design decisions. Do not edit it by hand -
re-run the command. The 18 October 2026 audit is in [gap-analysis.md](gap-analysis.md)
and the current status is in [CLAUDE.md](../CLAUDE.md).

## API (from `docs/api/openapi.json`)

- **183** operations over **146** paths and **208** schemas.
- If this contract is stale, run `python -m scripts.export_openapi`.

| Tag | Operations |
|---|---|
| portal | 19 |
| quotes | 17 |
| leads | 13 |
| catalogue | 11 |
| user administration | 11 |
| opportunities | 10 |
| accounts | 9 |
| tickets | 9 |
| activities | 8 |
| invoices | 8 |
| knowledge | 8 |
| assistant | 7 |
| contacts | 7 |
| workflows | 7 |
| documents | 5 |
| notifications | 5 |
| orders | 5 |
| reports | 5 |
| customer relationships | 3 |
| identity | 3 |
| portal access | 3 |
| health | 2 |
| onboarding | 2 |
| portal-knowledge | 2 |
| voice | 2 |
| dashboard | 1 |
| platform | 1 |

## Database (live)

- Alembic revision: **0028**
- Tables in the current schema: **51**
- Tables with Row-Level Security: **2** (2 policies)

## Migrations (from `backend/alembic/versions/`)

- Migration files: **28**
- Heads: `0028`

## Web app (`frontend/src/app`)

- 68 pages and 8 route handlers.

| Route | Kind |
|---|---|
| `/` | page |
| `/accounts` | page |
| `/accounts/[id]` | page |
| `/accounts/[id]/edit` | page |
| `/accounts/health` | page |
| `/accounts/new` | page |
| `/api/auth/callback/keycloak` | route handler |
| `/api/auth/login` | route handler |
| `/assistant` | page |
| `/automation` | page |
| `/automation/[id]` | page |
| `/automation/new` | page |
| `/contacts` | page |
| `/contacts/[id]` | page |
| `/contacts/[id]/edit` | page |
| `/contacts/new` | page |
| `/documents` | page |
| `/documents/[id]/download` | route handler |
| `/invoices` | page |
| `/invoices/[id]` | page |
| `/knowledge` | page |
| `/knowledge/search` | page |
| `/leads` | page |
| `/leads/[id]` | page |
| `/leads/[id]/edit` | page |
| `/leads/new` | page |
| `/login` | page |
| `/notifications` | page |
| `/notifications/settings` | page |
| `/opportunities` | page |
| `/opportunities/[id]` | page |
| `/opportunities/[id]/edit` | page |
| `/opportunities/new` | page |
| `/orders` | page |
| `/orders/[id]` | page |
| `/orders/[id]/edit` | page |
| `/orders/new` | page |
| `/pending` | page |
| `/platform` | page |
| `/portal` | page |
| `/portal/accounts/[id]` | page |
| `/portal/assistant` | page |
| `/portal/documents/[id]/download` | route handler |
| `/portal/invoices` | page |
| `/portal/invoices/[id]` | page |
| `/portal/knowledge` | page |
| `/portal/orders` | page |
| `/portal/orders/[id]` | page |
| `/portal/quotes` | page |
| `/portal/quotes/[id]` | page |
| `/portal/quotes/[id]/pdf` | route handler |
| `/portal/tickets` | page |
| `/portal/tickets/[id]` | page |
| `/portal/tickets/new` | page |
| `/print/quotes/[id]` | page |
| `/products` | page |
| `/products/[id]` | page |
| `/products/new` | page |
| `/products/price-books/[id]` | page |
| `/profile` | page |
| `/quotes` | page |
| `/quotes/[id]` | page |
| `/quotes/[id]/edit` | page |
| `/quotes/[id]/pdf` | route handler |
| `/quotes/new` | page |
| `/quotes/settings` | page |
| `/reports` | page |
| `/reports/[key]/csv` | route handler |
| `/reports/builder` | page |
| `/reports/builder/csv` | route handler |
| `/tasks` | page |
| `/tasks/calendar` | page |
| `/tickets` | page |
| `/tickets/[id]` | page |
| `/tickets/new` | page |
| `/users` | page |

## Tests

- Backend test files: **68**
- Frontend component test files: **14**
- Playwright end-to-end specs: **20**

## Documentation

- Markdown documents under `docs/`: **45** (12 in `docs/adr/`)
