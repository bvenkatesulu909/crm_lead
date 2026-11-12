# Project inventory (generated)

*Generated on 2026-11-12 by `python -m scripts.report_inventory` (run in `backend/` with the venv active).*

This file records counts and routes, not design decisions. Do not edit it by hand -
re-run the command. The 18 October 2026 audit is in [gap-analysis.md](gap-analysis.md)
and the current status is in [CLAUDE.md](../CLAUDE.md).

## API (from `docs/api/openapi.json`)

- **247** operations over **198** paths and **295** schemas.
- If this contract is stale, run `python -m scripts.export_openapi`.

| Tag | Operations |
|---|---|
| portal | 21 |
| quotes | 18 |
| leads | 13 |
| catalogue | 11 |
| communications | 11 |
| user administration | 11 |
| assistant | 10 |
| knowledge | 10 |
| opportunities | 10 |
| accounts | 9 |
| contracts | 9 |
| tickets | 9 |
| activities | 8 |
| documents | 8 |
| invoices | 8 |
| contacts | 7 |
| qualifier | 7 |
| workflows | 7 |
| webcheck | 6 |
| approvals | 5 |
| notifications | 5 |
| orders | 5 |
| reports | 5 |
| buyer-memory | 4 |
| agents | 3 |
| customer relationships | 3 |
| identity | 3 |
| portal access | 3 |
| voice | 3 |
| account-research | 2 |
| deal-desk | 2 |
| health | 2 |
| onboarding | 2 |
| portal-knowledge | 2 |
| public chat | 2 |
| dashboard | 1 |
| lead-agent | 1 |
| platform | 1 |

## Database (live)

- Alembic revision: **0059**
- Tables in the current schema: **72**
- Tables with Row-Level Security: **68** (68 policies)

## Migrations (from `backend/alembic/versions/`)

- Migration files: **59**
- Heads: `0059`

## Web app (`frontend/src/app`)

- 81 pages and 15 route handlers.

| Route | Kind |
|---|---|
| `/` | page |
| `/accounts` | page |
| `/accounts/[id]` | page |
| `/accounts/[id]/edit` | page |
| `/accounts/[id]/links` | route handler |
| `/accounts/health` | page |
| `/accounts/new` | page |
| `/accounts/search` | route handler |
| `/api/auth/callback/keycloak` | route handler |
| `/api/auth/login` | route handler |
| `/api/public-chat` | route handler |
| `/api/voice/speak` | route handler |
| `/api/voice/transcribe` | route handler |
| `/approvals` | page |
| `/approvals/[id]` | page |
| `/assistant` | page |
| `/assistant/conversations` | route handler |
| `/assistant/conversations/[id]/turns` | route handler |
| `/automation` | page |
| `/automation/[id]` | page |
| `/automation/agents` | page |
| `/automation/new` | page |
| `/automation/qualifier` | page |
| `/chat` | page |
| `/communications` | page |
| `/communications/templates` | page |
| `/communications/templates/[id]` | page |
| `/communications/templates/new` | page |
| `/contacts` | page |
| `/contacts/[id]` | page |
| `/contacts/[id]/edit` | page |
| `/contacts/new` | page |
| `/contracts` | page |
| `/contracts/[id]` | page |
| `/contracts/[id]/edit` | page |
| `/contracts/new` | page |
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

- Backend test files: **201**
- Frontend component test files: **43**
- Playwright end-to-end specs: **37**

## Documentation

- Markdown documents under `docs/`: **88** (30 in `docs/adr/`)
