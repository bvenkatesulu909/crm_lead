# Web frontend (`frontend/`)

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS 4, talking to the FastAPI
backend. Status: staff and portal screens for every shipped module (login/session, dashboards,
leads, accounts, contacts, pipeline, tasks, quotes, orders, invoices, tickets, documents,
reports, notifications, automation, users, assistant). Open UI gaps are tracked in
[docs/gap-analysis.md](gap-analysis.md).

## How it fits together (Backend-for-Frontend)

```
Browser ──cookie (encrypted, httpOnly)──► Next.js server ──Bearer access token──► FastAPI
   │                                           │  ▲
   └── login page on Keycloak ◄─ redirect ─────┘  └── tokens from Keycloak (code + PKCE + secret)
```

- The **browser never holds a token**. It holds one cookie, `crm_session`: AES-256-GCM encrypted
  (only the Next.js server has the key), `httpOnly` (page JavaScript can't read it),
  `SameSite=Lax` (not sent on cross-site posts/fetches). Nothing goes to `localStorage`.
- All data is fetched **on the Next.js server** (Server Components) and all changes go through
  **Server Actions**, which Next.js protects against cross-site requests (Origin check).
- **The frontend makes no security decisions.** It hides links the user can't use, but every
  request is authorized again by the API (role, tenant, record). Typing a URL directly gets
  the backend's 403/404 (tested end-to-end).

## Login, session, logout

| Step | Where | What happens |
|---|---|---|
| 1 | `src/proxy.ts` | No valid session → redirect to `/login?returnTo=…` |
| 2 | `/api/auth/login` | Creates PKCE verifier + `state` + `nonce`, keeps them in a 10-minute encrypted cookie, redirects to Keycloak |
| 3 | Keycloak | User enters the password **on Keycloak's page** (the CRM never sees it) |
| 4 | `/api/auth/callback/keycloak` | Checks `state`, exchanges the code with the PKCE verifier and client secret, validates the ID token (`nonce`), stores access + refresh tokens in `crm_session` |
| 5 | `src/proxy.ts` | Before each page: if the 5-minute access token has < 30 s left, refresh it (one shared refresh per token: Keycloak refresh tokens are single-use) |
| 6 | Sign out (Server Action) | Deletes the cookie **and** ends the Keycloak session server-to-server, so the next login asks for the password again |

`returnTo` only accepts paths on this site (no open redirects). Library: the certified
[`openid-client`](https://github.com/panva/openid-client) for OIDC and
[`jose`](https://github.com/panva/jose) for cookie encryption.

## Decisions

| Decision | Why |
|---|---|
| `openid-client` + `jose` instead of Auth.js | Small, explicit, certified OIDC client; every step is visible and tested; no beta dependency. |
| Only access + refresh token in the cookie | All three Keycloak tokens encrypted exceed the 4 KB cookie limit; the ID token isn't needed after login. |
| Cache Components **off** | Every screen is per-user; rendering each request on the server means nothing can be cached across users. |
| Search/filters/pagination in the URL (plain GET form) | Works without JavaScript, shareable, back button works. |
| Validation in the browser **and** on the server (same zod schema) **and** in the API | Fast feedback; the server never trusts the browser; the API never trusts the app. |

## Screens

| Route | Screen | Notes |
|---|---|---|
| `/login` | Sign-in | Messages for cancelled/expired/failed sign-in and after sign-out |
| `/` | Dashboard | Role dashboards (executive / manager / rep): lead counts, pipeline, follow-ups, revenue, orders and support - in the user's scope; plus the module catalogue with honest build status (19 modules). Only modules that work and that the role may use are links |
| `/leads` | Lead list | Search (name, company, e-mail), status/source filters, sort, 20 per page; empty, no-results, error and no-access states |
| `/leads/new` | Create lead | Labelled fields, required marker, per-field errors with `aria-describedby`, focus moves to the first error, backend errors shown with a reference ID |
| `/leads/[id]` | Lead details | Details, owner, timeline (activities + automatic events), ownership history, conversion result. Action bar shows only what the role and status allow: Edit, Assign, Mark as contacted, Qualify, Disqualify, Convert |
| `/leads/[id]/edit` | Edit lead | Same form as create, pre-filled; sends the `version` it loaded, so a concurrent change gives a clear "changed by someone else" error instead of overwriting |
| `/accounts`, `/accounts/new`, `/accounts/[id]/edit` | Customer accounts | Search (name, account number), status filter, 20 per page, owner names; create/edit with segment, owner and parent account (same record-level rules as the API) |
| `/accounts/[id]` | Account details | Profile, owner, parent account, contacts card, documents, quotes, deals, activities and history of converted leads |
| `/accounts/health` | Customer health | At-risk list from customer health scores (see [customer-relationships.md](customer-relationships.md)) |
| `/contacts`, `/contacts/new`, `/contacts/[id]`, `/contacts/[id]/edit` | Contacts | List/search, detail with consent and history, create/edit (see [accounts-contacts.md](accounts-contacts.md)) |
| `/opportunities` | Pipeline board | Kanban with drag & drop and "Move to", totals per stage (see [pipeline-activities.md](pipeline-activities.md)) |
| `/opportunities/new`, `/opportunities/[id]`, `/opportunities/[id]/edit` | Deal details / edit | Amount, stage history, won/lost/reopen, quote cards |
| `/tasks`, `/tasks/calendar` | Tasks and calendar | Tasks, follow-ups and logs linked to records; overdue, reminders bell, calendar view |
| `/products`, `/products/new`, `/products/[id]` | Products | Catalogue: managers maintain, sales/support read (see [quotes-catalog.md](quotes-catalog.md)) |
| `/products/price-books/[id]` | Price book | Entries used to price quotes |
| `/quotes`, `/quotes/new`, `/quotes/[id]`, `/quotes/[id]/edit` | Quotes | Lines, discounts (approval above the tenant limit - four eyes), revisions, status, send by e-mail with the PDF |
| `/quotes/settings` | Quote settings | The organisation's approval limit (tenant admins) |
| `/print/quotes/[id]`, `/quotes/[id]/pdf` | Printable quote / PDF | Print view; stored PDF download through a route handler (no token in the browser) |
| `/orders`, `/orders/new`, `/orders/[id]`, `/orders/[id]/edit` | Orders (staff) | See [orders.md](orders.md) |
| `/invoices`, `/invoices/[id]` | Invoices, payments, credit notes (staff) | See [invoices.md](invoices.md) |
| `/tickets`, `/tickets/new`, `/tickets/[id]` | Support (staff) | See [support.md](support.md) |
| `/documents`, `/documents/[id]/download` | Documents | Upload versions on accounts/deals; download through a route handler with an authorization check (see [documents.md](documents.md)) |
| `/knowledge` | Knowledge (staff) | Upload PDF/DOCX/TXT/Markdown, see the indexing status, delete; tenant admins manage, all staff read (see [rag-knowledge-base.md](rag-knowledge-base.md)) |
| `/knowledge/search` | Search & ask (staff) | Hybrid passage search with reranked results and a question box whose answer cites the exact passages; permission `knowledge:read` |
| `/reports`, `/reports/builder` | Reports | Standard reports and the report builder (see [reports.md](reports.md)) |
| `/reports/[key]/csv`, `/reports/builder/csv` | CSV export | Route handlers; audit entry and formula-injection protection |
| `/notifications`, `/notifications/settings` | Notifications | Inbox, mark read, e-mail notification settings (see [workflows.md](workflows.md)) |
| `/automation`, `/automation/new`, `/automation/[id]` | Automation rules | Trigger → conditions → actions, run log (tenant admins) |
| `/users` | Users (Tenant Admin) | See [onboarding.md](onboarding.md): staff list, add staff member, change role, deactivate/reactivate, resend invitation, sign-up code, access requests |
| `/platform` | Organisations (Super Admin) | List organisations, create one with its first Tenant Admin |
| `/pending` | Waiting for access | People signed in without CRM access: enter sign-up code, see request status, "Continue" after approval (refreshes the token), deactivated notice |
| `/profile` | Employee profile | Name, e-mail, organisation, roles, what the role allows (plain language), link to Keycloak's own page for password / two-step sign-in, sign out |
| `/portal` | Customer portal home | Customers only (staff see "this area is for customers"). Lists ONLY the granted accounts; recent orders, invoices to pay, tickets, quotes and documents; link to the assistant |
| `/portal/accounts/[id]` | Customer's account | Customer-safe fields only. Another customer's account - same or other tenant - is a 404 |
| `/portal/orders`, `/portal/orders/[id]` | Order status (customers) | See [orders.md](orders.md) |
| `/portal/invoices`, `/portal/invoices/[id]` | Invoices and amount owed (customers) | See [invoices.md](invoices.md) |
| `/portal/quotes`, `/portal/quotes/[id]`, `/portal/quotes/[id]/pdf` | Quotes (customers) | See sent quotes, accept or decline, download the PDF |
| `/portal/tickets`, `/portal/tickets/new`, `/portal/tickets/[id]` | Support (customers) | See [support.md](support.md) |
| `/portal/documents/[id]/download` | Document download (customers) | Public documents of granted accounts only |
| `/portal/assistant` | AI assistant (customers) | See [assistant.md](assistant.md): chat about own orders/invoices/tickets, prepared tickets to confirm, "not available" without an API key |
| `/portal/knowledge` | Help & policies (customers) | Ask the knowledge base; only customer-visible public help plus chunks of accounts in the customer's `portal_access_grants`; internal documents/staff are rejected by the API |
| `/api/auth/login`, `/api/auth/callback/keycloak` | OIDC login handlers | Authorization Code + PKCE; stores the encrypted `crm_session` cookie |
| `/_not-found`, error pages | Not found / error | Friendly pages; errors show a reference ID |

**Confirmation for sensitive actions:** every change on the lead page (assign, contacted,
qualify, disqualify, convert) opens a native `<dialog>` that explains the consequence first —
convert says "This cannot be undone", disqualify requires a reason, assign names the current
owner. Cancel or Escape changes nothing. Errors from the API (e.g. an invalid status change)
are shown inside the dialog.

Layout: sidebar (desktop) / slide-in menu (mobile), top bar with user menu (name, roles,
sign out), "Skip to main content" link, visible focus ring, Escape closes menus.
Navigation is grouped by module and filtered by role in `src/lib/permissions.ts` (display only;
the API decides), and customers are redirected from every staff page to `/portal`, which has its
own simpler layout.

## Key shared files

This is a map of the shared building blocks, not a full file index. The **Screens** table above
covers every route; per-module screens live under `src/app/` (for example `src/app/(app)/contacts/`,
`src/app/(app)/quotes/`, `src/app/portal/`) and each module documents its own files in `docs/*.md`.

| Path | Purpose |
|---|---|
| `src/proxy.ts` | Login gate + silent token refresh before each page |
| `src/lib/server/config.ts` | Reads and validates `.env.local` (server only) |
| `src/lib/server/session.ts` | Encrypt/decrypt the session and login-state cookies |
| `src/lib/server/oidc.ts` | Keycloak: start login, finish login, refresh, end session |
| `src/lib/server/api.ts` | Calls FastAPI from the server with the user's token; turns errors into `ApiError` |
| `src/app/api/auth/login/route.ts`, `…/callback/keycloak/route.ts` | The two login endpoints |
| `src/app/actions/auth.ts` | Sign-out Server Action |
| `src/lib/permissions.ts` | Role-based navigation (display only) |
| `src/app/(app)/accounts/` | Account list (+ URL parameters) and account details |
| `src/app/(app)/profile/page.tsx` | Employee profile |
| `src/app/portal/` | Customer portal layout, home, account page, tickets |
| `src/app/(app)/tickets/` | Staff support screens and Server Actions |
| `src/components/tickets.tsx`, `src/components/ticket-forms.tsx` | Ticket badges, conversation thread, ticket and reply forms |
| `src/lib/ticket-rules.ts`, `src/lib/validation/tickets.ts` | Status buttons to show (display only) and ticket input rules |
| `src/app/(app)/orders/`, `src/app/portal/orders/` | Staff order screens + Server Actions; customer order status |
| `src/components/orders.tsx`, `src/components/order-form.tsx` | Order badges, money format, lines table, progress steps; draft form with line editor |
| `src/lib/order-rules.ts`, `src/lib/order-math.ts`, `src/lib/validation/orders.ts` | Order buttons to show (display only), exact cent preview, order input rules |
| `src/lib/lead-rules.ts` | Which lead buttons to show (copy of backend transitions; display only) |
| `src/components/action-dialog.tsx` | Confirmation dialog + accessible dialog fields |
| `src/components/lead-form.tsx` | Lead form shared by create and edit |
| `src/app/(app)/leads/[id]/` | Details page, action bar, edit page, Server Actions (edit, assign, status, convert) |
| `src/lib/validation/lead-actions.ts` | Input rules for the dialogs (same limits as the API) |
| `src/lib/modules.ts`, `src/components/module-grid.tsx` | Dashboard module catalog: name, description, status, plan phase, required permissions. Update a module's `status`/`href` here when it ships |
| `src/lib/validation/lead.ts` | Lead form rules (shared by browser and server) |
| `src/lib/api-error.ts`, `src/lib/api-types.ts` | Error → readable message; API response types (mirror `docs/api/openapi.json`) |
| `src/components/` | App shell, user menu, pagination, shared UI (alerts, badges, empty states) |
| `src/app/(app)/` | Signed-in pages: dashboard, leads, new lead; loading and error screens |
| `src/**/*.test.ts(x)` | Component and unit tests (Vitest + Testing Library) |
| `e2e/` | End-to-end tests (Playwright) against the real stack |

## Configuration (`frontend/.env.local`, git-ignored)

See `frontend/.env.example`: `APP_BASE_URL`, `API_BASE_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET` (= `CRM_WEB_CLIENT_SECRET` in `infrastructure\.env`), `SESSION_SECRET`
(32 random bytes), and `E2E_USER_PASSWORD` for end-to-end tests only.

## Run and test (Windows CMD)

```bat
cd E:\crm-lead\frontend
npm install
npm run dev
```

Open http://localhost:3000 (the backend must run on port 8000 and Keycloak on 8080).

```bat
npm run lint
npm run typecheck
npm test
npm run test:e2e
```

`npm run test:e2e` starts the backend and the web app if they aren't running (Docker services
must be up). The slow token-refresh test runs only with `set E2E_SLOW=1`.

## Not done yet

- Generated API types from `docs/api/openapi.json` instead of hand-written ones.
- Content-Security-Policy header (needs nonce support for Next.js scripts).
- Staff AI assistant chat (the portal assistant exists; see `docs/assistant.md`).
