# The "Website chat" report: measuring the pilot (follow-up of CRM-113)

**Status:** design accepted 2026-11-03 (all four answers in section 5 as recommended). PR1 (the counter) built; PR2 and PR3 not started.
**Kind:** a short design, not an ADR. It adds one standard report to the Reports module
([reports.md](reports.md)) and one small counter table. It changes no accepted ADR.

## 1. Why

The client case study ([case-study-real-estate-leads.md](case-study-real-estate-leads.md)) has a results
table that must be filled from **data, not memory**: time from the first message to a saved lead, share of
chats that end with a lead, leads with budget and area, time to the first call, suggestions approved vs.
rejected, and AI cost per saved lead. The same figures are what the agency's managers want to see. So
instead of a private script, they become a normal **report** that managers and administrators can open,
filter by period and download as CSV, under the same access rules as every other report.

## 2. What exists today (and the gap)

| Figure | Where the data lives | Problem |
|---|---|---|
| First message to saved lead | `public_chat_messages.created_at` (first visitor message) and the lead's `created_at` | none |
| Chats that end with a lead | `public_chat_sessions` (with or without `lead_id`) | **Conversations without a lead are deleted after 30 quiet days** (`CRM_PUBLIC_CHAT_RETENTION_DAYS`, a privacy rule). The *denominator* disappears: a report for a period older than a month would show every chat as a success. |
| Leads with budget and area | `leads.budget_min_inr`, `budget_max_inr`, `location`, `property_type`, `source = web` | none |
| New lead to first call | `lead_activities` (kind `call`) and the audit entry `lead.status_changed` (structured `old` / `new` status; the timeline text "Status changed from new to contacted" is not parsed) | none, but "first call" needs one written definition |
| Qualifier suggestions approved vs. rejected | `agent_actions` where `agent = qualifier`, by status | none |
| AI cost per saved lead | `agent_usage` (tokens per organisation, agent and **month**) times the two prices | tokens are stored per month, not per day |

## 3. The change

1. **A tiny anonymous counter** `public_chat_daily_stats` (organisation, day, conversations started, leads
   saved): two numbers per day, no visitor address, no text, no token, no lead id. The chat service adds 1
   when a conversation starts and when it saves its lead. Row-level security as on every tenant table. It
   keeps the funnel true after the conversations themselves are cleaned up, **without** keeping any more
   personal data than today. New migration; the counters start counting on the day it is applied (earlier
   chats cannot be recovered - which is why this should go in **before** the pilot).
2. **A standard report "Website chat"** (`GET /api/v1/reports/chat?start=&end=`, CSV too), each figure
   computed by the module that owns the data, as the other reports are:
   - `public_chat`: conversations started, leads saved, share, and the median and 90th-percentile seconds
     from the first visitor message to the saved lead (only for conversations still stored, said in the
     report);
   - `leads`: web leads in the period and the share with budget, area and property type; median hours from
     lead to first call (definition below);
   - `approvals`: Qualifier suggestions in the period by outcome (approved, rejected, expired, failed) and the
     median minutes until someone decided;
   - `agents`: the estimated AI cost of the chat and the Qualifier for the whole months the period touches,
     divided by the web leads of those months - labelled an estimate, as on the AI agents page.
3. **Who sees it:** sales managers and tenant administrators (it is an organisation-wide view; an agent sees
   only their own leads, so the report would be wrong for them). Aggregates only: no name, phone, message or
   lead id appears in the report or the CSV. The CSV download is audited like the others.
4. **The page** is a new card on *Reports*, with the usual period picker, a short "how to read this" line under
   each figure, and the CSV button.
5. **Docs:** `docs/reports.md` gets the row and the definitions; the case study's results table gets a column
   "where this number comes from" pointing at the report.

### Definitions (written in the report so nobody argues later)

- *First call*: the earlier of the first logged **call** on the lead and the lead's first change to status
  **contacted**.
- *Lead with details*: a web lead that has a budget (minimum or maximum), a location and a property type.
- *Period*: UTC days, like the other reports; the AI cost row uses whole calendar months and says so.

## 4. What stays out (on purpose)

- No visitor-level or lead-level listing (the report builder already exports leads under their access rules).
- No new personal data and no longer retention of conversations.
- No comparison with the "before" numbers: those come from the client and go into the case study by hand.
- No dashboard tile, no e-mailed report, no alert.

## 5. Questions for the owner - answered 2026-11-03: all four as recommended

1. **A report in the Reports module** (managers and administrators, CSV, audited), rather than a script only
   you can run? *Recommended: yes* - the client's managers get the same numbers, under the same access rules.
2. **Add the anonymous daily counter** so the "chats that end with a lead" share stays correct after the
   30-day cleanup, and apply it **before** the pilot starts? *Recommended: yes.* The alternative is to run the
   report at least every 30 days and copy the numbers out by hand.
3. **"First call" = the earlier of the first logged call and the first change to "contacted"**? *Recommended: yes.*
4. **AI cost per lead from the monthly estimate** (whole months, labelled an estimate)? *Recommended: yes.*

## 6a. What PR1 built (2026-11-03)

- Table `public_chat_daily_stats` (migration 0049): primary key (organisation, UTC day), the two counters and
  `updated_at` - nothing that could identify a visitor, a message or a lead. Forced row-level security. Two
  locks: a trigger that refuses any UPDATE that would lower a counter (it binds every role), and no DELETE or
  TRUNCATE privilege for the application role.
- `repository.count_event` adds to the day's row in one `INSERT ... ON CONFLICT DO UPDATE` statement, so two
  requests at the same moment add up. The chat service calls it when a conversation is created and when its
  lead is saved (the existing "already saved" early return means once per conversation), inside the request's
  own transaction. A message refused before any conversation exists, or sent with an unknown token, counts for
  nothing.
- Tests (`tests/db/test_public_chat_stats.py`, 15): a conversation counts once however many messages; each
  new one counts; a lead counts once even when the visitor keeps talking; refused and unknown-token messages
  count for nothing; the day is the UTC day (checked across midnight); the numbers survive the clean-up that
  deletes the conversations; the table has exactly the five columns; one organisation never sees another's;
  two increments add up; counters cannot be lowered, set negative or deleted; the application role has no
  DELETE or TRUNCATE privilege. Six deliberate breaks of the code were all caught. The row-level-security
  guard test covers the new table automatically.
- The development database was upgraded to 0049 (`rls_audit`: no table readable without a tenant context).

## 6. Steps (each stops for review, tests first)

| Step | Content |
|---|---|
| PR1 (done) | The counter table (migration, row-level security, counted by the chat service), tests incl. tenant isolation and "no personal data in the table" |
| PR2 | The figures in each module's `api.py` and the `chat` report in the Reports module (API, CSV, audit), tests incl. access by role, tenant isolation and the definitions |
| PR3 | The report page, `docs/reports.md`, the case study's "where this comes from" column |
