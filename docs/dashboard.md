# Dashboards (executive, sales manager, sales representative)

The home page (`/`) shows a dashboard built from **real records in the database**; nothing on it is mock data.
One endpoint serves all three views: `GET /api/v1/dashboard`. The full contract is in
[`docs/api/openapi.json`](api/openapi.json).

## Who sees what

| Role | Views | What is included |
|---|---|---|
| Tenant admin | **Executive** (default), Sales manager, My sales | everything below + invoiced, payments received, outstanding, overdue, orders, open tickets |
| Sales manager | **Sales manager** (default), My sales | sales figures for the whole team + the "Sales team" table + the sales rep filter |
| Sales agent | **My sales** only | the same sales figures, limited to records they own |
| Support agent, customer, platform admin | none | the home page stays as before (the API answers 403) |

New permissions in `app/core/auth/rbac.py`:
- `dashboard:executive`, `dashboard:sales:all` and `dashboard:sales:own`;
- `opportunity:read:all` and `opportunity:read:own`, which the pipeline figures use.

## How the figures are made (and why they can be trusted)

**Each module computes its own figures** in its own `metrics.py`, using **its own record-level policy**:
- `leads/metrics.py`
- `accounts/metrics.py`
- `sales/metrics.py`
- `invoices/metrics.py`
- `orders/metrics.py`
- `support/metrics.py`

Each is exported through the module's `api.py`. The `dashboard` module has no tables of its own; it only combines those results.

So a number on the dashboard can never include a record the user could not open in the module itself. For example:
- an agent's "Customers" count is exactly their account list;
- other tenants are never counted.

All counting happens in SQL (`COUNT`, `SUM`, `GROUP BY`); records are not loaded and filtered in Python.

**Money is never converted.** Totals are per currency, for example `€1,500.50 · US$20.00`.
- An opportunity without an amount is counted under "without an amount".
- It is not counted as 0.00.

## Filters

| Filter | URL (web) | API | Rules |
|---|---|---|---|
| Period | `?range=7d / 30d / 90d / month / year` or `?range=custom&from=YYYY-MM-DD&to=YYYY-MM-DD` | `start`, `end` | Default: the last 30 days. Both days are included. UTC days. The API rejects `end < start` and more than 3 years with **422** `invalid_filter`. |
| Sales rep ("team filter") | `?rep=<user id>` | `owner_id` | Manager and executive views only. Must be a staff member of the same tenant, otherwise **422**. A sales agent naming anyone else gets **403**. |
| View | `?view=executive / manager / representative` | `view` | A view the role does not have gets **403**. |

The filters are in the URL, so a filtered dashboard can be bookmarked or shared. The filter form is a plain HTML GET form and works without JavaScript.

**Period vs "now".** Two kinds of figures appear:
- **Period figures** depend on the chosen dates: leads created, qualified, converted in the period, new customers, invoiced, payments received, orders confirmed, tickets opened, activity feed.
- **"Now" figures** are always the current state and are marked "(now)": open opportunities and pipeline by stage, follow-ups due, open leads, outstanding/overdue, open tickets.

## Honest substitutes (until the real features exist)

| Requested | What it shows today | Real feature comes in |
|---|---|---|
| Pending tasks and follow-ups | **Follow-ups:** open leads (new/contacted/qualified) with **no activity for 7 days or more**. Last touch = the newest lead activity, or the creation date. | Phase 9: tasks and reminders. |
| Team filter | **Sales rep filter.** The CRM has no teams yet. | Phase C (teams); the filter will then gain "team". |
| Opportunities | Opportunities created by lead conversion. There is no opportunity screen yet, so the pipeline tiles are not links. | Phase 8 |

## Code map

| Piece | File |
|---|---|
| Endpoint | `backend/app/modules/dashboard/router.py` (`GET /api/v1/dashboard`) |
| Combining + view/filter rules | `backend/app/modules/dashboard/service.py` |
| Response schema | `backend/app/modules/dashboard/schemas.py` |
| Shared types (period, money, activity item) | `backend/app/core/reporting.py` |
| Web page | `frontend/src/app/(app)/page.tsx` |
| Web building blocks | `frontend/src/components/dashboard.tsx` |
| URL/filter logic | `frontend/src/lib/dashboard.ts` |

## Tests

- **Backend:** `tests/db/test_dashboard_api.py` has 26 tests on real PostgreSQL with known records, checking exact figures. They cover:
  - each role's views; refused roles and views;
  - a rep seeing only their own records;
  - manager and rep filters;
  - a rep filter pointing at another tenant, a random ID or a customer;
  - tenant isolation; custom and single-day periods; invalid periods;
  - executive revenue, including a reversed payment, plus orders and tickets;
  - the opportunity policy on its own.

  Eight deliberate bugs (mutation checks) were each caught by a failing test.
- **Unit:** `frontend/src/lib/dashboard.test.ts` covers presets, URL parsing, the API query, links and formatting.
- **E2E:** `frontend/e2e/dashboard.spec.ts` runs against the real stack:
  - rep: a new lead is counted at once;
  - manager: period presets, custom dates and the rep filter;
  - executive: business figures;
  - support staff: no dashboard.
