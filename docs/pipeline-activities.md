# Opportunity pipeline and activities and tasks (Phase D)

This phase adds sales deals with a Kanban pipeline, plus tasks, follow-ups, logged interactions, reminders and a calendar.
Everything is stored in PostgreSQL. Nothing on these screens is mock data.

## Opportunities (`/opportunities`)

| Screen | What you can do |
|---|---|
| **Pipeline board** | Four columns (Prospecting 10 %, Qualification 25 %, Proposal 50 %, Negotiation 75 %).<br>Each column shows its count, value and **weighted value** (value × probability) per currency.<br>Move a deal by **dragging its card** or with its **"Move to…"** menu (works with the keyboard).<br>Below the board: deals **won and lost in the last 30 days**.<br>Filters: search, deal owner (managers). |
| **New / Edit** | Name, account, primary contact (must work at that account), stage, estimated value + currency, expected close date, owner (managers), next step, description. |
| **Deal page** | Stage stepper; **Move stage**, **Mark as won**, **Mark as lost**, **Reopen** (managers); stage history; activities. |

**Rules** (checked by the API; the screens only show the buttons):
- Only the four open stages are used for moving. Closing is done with **won** (needs a deal value) or **lost** (needs a reason). Both set the close date on the server.
- A closed deal is read-only. Only managers and admins can **reopen** it; reopening clears the close date and the lost reason, but the history keeps them.
- Sales agents see and change their own deals. Managers and admins see and change all deals. Support staff and customers have no access.
- Every stage change is stored in `opportunity_stage_changes`. That table is insert-only for the app user, like the audit log. Every change is also audited.
- Probabilities are fixed per stage. Pipelines and stages that each organisation configures itself come with the administration phase.

## Activities and tasks (`/tasks`, record pages)

One `activities` table holds two kinds of item:
- **Open items:** a *task*, or a planned *call / meeting / e-mail* (a **follow-up**), with a due time, an optional **reminder** and a priority.
- **Logged items:** something that happened (*call, meeting, e-mail, note*), with when it happened and its outcome. Notes are always logged.

An activity can be linked to **one** lead, account, contact or opportunity, or to none (a personal to-do). Each link is a real foreign key to a record of the same organisation.

| Where | What |
|---|---|
| **Account, contact, opportunity pages** | "Activities and follow-ups": plan a task or follow-up, or log what happened. The full timeline of that record. Done / Cancel / Reopen. |
| **Lead pages** | "Tasks and follow-ups": planning only. Calls and notes on leads stay in the lead's own timeline from Phase B, so there is only one place to log them. |
| **Tasks** | Your open items grouped **Overdue · Due today · Upcoming · No due date** (in *your* local time). Recently finished items. A "New task" form. Managers can switch to **Everyone**. |
| **Calendar** | A month view of items by due time, in your local time. Managers can switch to Everyone. |
| **Header bell** | A count of your open items that are overdue, due within 24 hours, or past their reminder time. Each item is counted once. |

**Rules:**
- **Who sees what:**
  - Sales agents and support staff see items assigned to them or created by them.
  - Agents also see items on records they own (their leads, accounts, deals, and the contacts at their accounts).
  - Managers and admins see all items.
  - Linking to a record you can't see answers **404**, as if it didn't exist.
- **Assigning:** giving a task to a colleague needs `activity:assign` (managers and admins). The assignee must be an active colleague in the same organisation. Reassignments are written to the audit log.
- **Changes:** only open items can be edited, completed or cancelled. Done or cancelled items can be reopened, except notes.
- **Dates:** all times are sent with a time zone, and the browser converts what you type. "Today" and the calendar days follow your own time zone.

### Reminders: what works now and what comes next
- **Now:** reminders appear *inside the CRM*, in the header bell, the Tasks page groups and the "Overdue" badges.
- **E-mail reminders** need a background worker, which comes in **Phase C** (outbox + worker). Until then no e-mail is sent.

## New permissions (`app/core/auth/rbac.py`)

| Permission | Tenant admin | Sales manager | Sales agent | Support |
|---|:-:|:-:|:-:|:-:|
| `opportunity:write:all` | ✓ | ✓ | | |
| `opportunity:write:own` | | | ✓ | |
| `activity:read:all`, `activity:write:all`, `activity:assign` | ✓ | ✓ | | |
| `activity:read:own`, `activity:write:own` | | | ✓ | ✓ |

## API (see `docs/api/openapi.json`)

| Method | Path | Notes |
|---|---|---|
| GET | `/opportunities` | Filters: `q`, `account_id`, `owner_id`, `stage`. |
| GET | `/opportunities/board` | Columns with counts and per-currency value and weighted value (counted in SQL). |
| POST | `/opportunities` | Create a deal. |
| GET | `/opportunities/{id}` | One deal. |
| PATCH | `/opportunities/{id}` | Open deals only. |
| POST | `/opportunities/{id}/stage` | Move between open stages. |
| POST | `/opportunities/{id}/won` | Needs a deal value. |
| POST | `/opportunities/{id}/lost` | Needs a reason. |
| POST | `/opportunities/{id}/reopen` | Managers and admins only. |
| GET | `/opportunities/{id}/stages` | Stage history. |
| GET | `/activities` | Filters: `mine`, `assignee_id`, `status`, `kind`, `due_from` / `due_to`, `overdue`, the four record links, `sort`. |
| GET | `/activities/reminders` | Your open items that need attention. |
| POST | `/activities` | Create a task or follow-up, or log an interaction. |
| GET | `/activities/{id}` | One activity. |
| PATCH | `/activities/{id}` | Open items only. |
| POST | `/activities/{id}/complete`, `/cancel`, `/reopen` | Change the item's status. |

**Database:** migration `0011` adds:
- to `opportunities`: `closed_at`, `lost_reason`, `next_step` and `description`, with rules that keep them consistent. Existing won or lost rows were back-filled.
- the tables `opportunity_stage_changes` and `activities`.

## Tests
- **Backend:** `tests/db/test_pipeline_activities_api.py` has 43 tests on real PostgreSQL. They cover:
  - the pipeline moves and won/lost/reopen rules;
  - the board totals per currency;
  - visibility and assignment rules, linking to hidden records, validation;
  - reminders and overdue items, and calendar ranges.

  15 deliberate bugs (mutation checks) were each caught by a failing test.
- **Unit:** `frontend/src/lib/pipeline.test.ts` covers the due labels, grouping by local day, the month grid, date conversion and the form rules.
- **E2E:** `frontend/e2e/pipeline-tasks.spec.ts` runs five journeys against the real stack:
  - deal to won, via the stage dialog, the "Move to…" menu and **drag and drop**;
  - lost needs a reason, and a manager reopens;
  - an overdue follow-up rings the bell, appears under Overdue and is completed;
  - the calendar;
  - lead pages are planning-only, and support has no pipeline.
