# Reports and the report builder (Phase 18, part 2)

Part 1 (done earlier) is the role dashboards on the home page ([dashboard.md](dashboard.md)).
Part 2 adds **standard reports**, a **report builder** and **CSV downloads**. Open **Reports**
in the menu.

## Standard reports

Each one takes a **period** (default: last 30 days; at most 3 years, shown in UTC) and, for
managers and admins, a **sales rep**. Every report can be downloaded as CSV.

| Report | What it shows | Visible to |
|---|---|---|
| **Sales: win rate** | Deals closed in the period per sales rep and currency: won, lost, win rate %, won value, average won deal | sales roles |
| **Leads: conversion** | Leads created in the period by source: converted, unqualified, still open, conversion % (with a total row) | sales roles |
| **Revenue & quotes** | Invoiced and payments received per month (payments net of reversals); orders confirmed per month; quotes sent / accepted / declined, acceptance %, average largest discount per rep | each part only for roles that may read invoices, orders or quotes |
| **Support: SLA & satisfaction** | Tickets per priority and per category: created, resolved, resolved late, on-time %, overdue now, average hours to resolve, average rating | roles that read tickets |

Amounts are **never added across currencies** (one row per currency). Only the reports and
sections a role may use are listed; a section a role may not read is left out.

## Report builder

*Reports → Report builder*: choose **what to list** (leads, accounts, contacts, deals, quotes,
orders, invoices, tickets, tasks), the **columns**, and filters (created from/until, status,
owner). The page shows a preview of the first 50 rows; **Download CSV** gives up to 5,000 rows.

## Rules that protect your data

- **The same access as the screens.** Every report and export is computed by the *owning
  module* with its own record-level policy: an agent only gets their own leads, customers and
  deals, support staff see all customers but no leads, and another organisation's records can
  never appear. Choosing another sales rep is only possible for managers and admins (an agent
  asking for someone else's figures gets 403).
- **Columns are a whitelist per record type.** Internal notes, tokens, IDs of other tenants
  and similar fields can't be exported; unknown columns are refused (422).
- **CSV exports are audited** (`report.exported`: who, which record type, columns, number of
  rows, filters). Previews are not.
- **CSV injection protection:** a text cell that starts with `=`, `+`, `-` or `@` (e.g. a
  customer named `=HYPERLINK(...)`) gets a leading `'` so Excel shows it as text and never runs
  it. The file starts with a UTF-8 marker so Excel reads umlauts correctly.
- Downloads are fetched by the Next.js server with your token (never by the browser), sent as
  attachments with `no-store`, so nothing is cached.

## API (all under `/api/v1/reports`, staff only)

| Method and path | What it does |
|---|---|
| `GET /reports` | the reports and record types available to you |
| `GET /reports/{key}?start=&end=&owner_id=` | one standard report (`sales`, `leads`, `revenue`, `support`) |
| `GET /reports/{key}/csv` | the same as CSV |
| `GET /reports/builder/{type}?columns=…&start=&end=&owner_id=&status=&limit=` | builder preview |
| `GET /reports/builder/{type}/csv` | builder download (audited) |

Error codes: `invalid_report_filter` (422: bad period, status or column), `report_not_found`
(404), 403 for another rep's figures or customers.

## How it is built

`app/core/reporting.py` holds the shared `Table`, `Column`, `ExportFilters` and `export_rows`
helper. Each module adds its figures to its own `metrics.py` (e.g. `sales/metrics.py:
win_loss_table`) and an `EXPORT` column list plus `export_table()` to its `api.py`. The
`reports` module only combines them, turns IDs into names and writes CSV.

## Not built yet

- Saved reports, scheduled e-mailed reports, charts in reports.
- Forecast and retention reports, a team filter (after teams exist), reports on marketing.
- Download of more than 5,000 rows at once.
